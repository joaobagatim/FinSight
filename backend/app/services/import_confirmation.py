"""Atomic one-time posting of the explicitly selected, versioned CSV review."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext

from sqlalchemy import select

from app.models import Account, ImportJob, ImportRow, Transaction
from app.schemas.import_confirmation import (
    ImportConfirmationContext,
    ImportConfirmationReceipt,
)
from app.services.allocations import availability_query, business_date
from app.services.import_duplicates import MAX_SOURCE_ROWS, duplicate_report, row_fingerprint
from app.services.import_review import (
    ImportReviewClosed,
    ImportReviewStale,
    review_query,
    review_response,
)
from app.services.imports import ImportConflict, ImportNotFound, ImportRejected, matching_query


def confirmation_etag(context):
    canonical = json.dumps(
        context.model_dump(mode="json", exclude={"etag"}), sort_keys=True, separators=(",", ":")
    )
    return '"' + hashlib.sha256(canonical.encode()).hexdigest() + '"'


def confirmation_digest(identity, etag, data):
    canonical = json.dumps(
        {"job_id": str(identity), "etag": etag, "acknowledgements": data.model_dump()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class ImportConfirmationService:
    def __init__(self, sessions, *, today=None):
        self.sessions = sessions
        self.today = today or business_date

    @staticmethod
    def job(session, owner, identity):
        job = session.scalar(
            select(ImportJob)
            .where(ImportJob.id == identity, ImportJob.user_id == owner)
            .with_for_update()
        )
        if job is None:
            raise ImportNotFound()
        return job

    def context(self, session, owner, job):
        if job.confirmation_result is not None:
            receipt = ImportConfirmationReceipt.model_validate(job.confirmation_result)
            result = ImportConfirmationContext(
                **receipt.model_dump(
                    exclude={"imported_rows", "not_imported_rows", "completed_at"}
                ),
                total_rows=receipt.imported_rows + receipt.not_imported_rows,
                selected_count=0,
                eligible=False,
                issues=["completed"],
                receipt=receipt,
            )
            result.etag = confirmation_etag(result)
            return result
        account = session.scalar(
            select(Account)
            .where(Account.id == job.account_id, Account.user_id == owner)
            .with_for_update()
        )
        if account is None:
            raise ImportNotFound()
        records = session.execute(
            review_query(owner, job.id)
            .order_by(ImportRow.row_number, ImportRow.id)
            .limit(MAX_SOURCE_ROWS + 1)
        ).all()
        if len(records) > MAX_SOURCE_ROWS:
            raise ImportRejected()
        selected = [review_response(row) for row in records if row.ImportRow.selected]
        day = max(self.today(), account.opening_date)
        position = session.execute(
            availability_query(owner, day).where(Account.id == account.id)
        ).one()
        with localcontext() as precision:
            precision.prec = 80
            income = sum((r.amount for r in selected if r.type == "income"), Decimal(0))
            expense = sum((r.amount for r in selected if r.type == "expense"), Decimal(0))
            delta = sum(
                (
                    r.amount if r.type == "income" else -r.amount
                    for r in selected
                    if r.transaction_date is not None and r.transaction_date <= day
                ),
                Decimal(0),
            )
            after = position.balance + delta
            free = after - position.reserved
            uncovered = max(Decimal(0), position.reserved - max(Decimal(0), after))
        issues = []
        if job.status != "review":
            issues.append("preview_closed")
        if not account.is_active or account.currency != "BRL":
            issues.append("account_unavailable")
        if not selected:
            issues.append("empty_selection")
        if any(not row.selection_eligible for row in selected):
            issues.append("invalid_selection")
        if any(row.linked or row.ImportRow.status == "imported" for row in records):
            issues.append("existing_financial_links")
        if job.total_rows != len(records) or job.imported_rows != 0:
            issues.append("counter_mismatch")
        duplicates = duplicate_report(session, owner, job.id)
        chosen = {row.id for row in selected}
        duplicates.items = [item for item in duplicates.items if item.row_id in chosen]
        result = ImportConfirmationContext(
            job_id=job.id,
            account_id=account.id,
            account_name=account.name,
            filename=job.filename,
            as_of=day,
            income_total=income,
            expense_total=expense,
            bank_balance_before=position.balance,
            bank_balance_after=after,
            reserved_amount=position.reserved,
            free_balance_after=free,
            uncovered_reserved_after=uncovered,
            invalid_rows=sum(row.ImportRow.status == "invalid" for row in records),
            future_rows=sum(
                row.transaction_date is not None and row.transaction_date > day for row in selected
            ),
            total_rows=len(records),
            selected_count=len(selected),
            selected_rows=selected,
            eligible=not issues,
            issues=issues,
            duplicates=duplicates,
            matching_files=session.scalar(
                matching_query(owner, account.id, job.file_checksum, excluded_id=job.id)
            ),
        )
        result.etag = confirmation_etag(result)
        return result

    def get(self, token, identity):
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            result = self.context(
                session, owner.user_id, self.job(session, owner.user_id, identity)
            )
        return result

    def confirm(self, token, identity, key, etag, data):
        digest = confirmation_digest(identity, etag, data)
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            job = self.job(session, owner.user_id, identity)
            previous = session.scalar(
                select(ImportJob).where(
                    ImportJob.user_id == owner.user_id, ImportJob.confirmation_key == key
                )
            )
            if previous is not None:
                if previous.id != identity or not hmac.compare_digest(
                    previous.confirmation_hash, digest
                ):
                    raise ImportConflict()
                result = ImportConfirmationReceipt.model_validate(previous.confirmation_result)
            else:
                if job.confirmation_key is not None:
                    raise ImportConflict()
                context = self.context(session, owner.user_id, job)
                if not hmac.compare_digest(context.etag, etag):
                    raise ImportReviewStale()
                if not context.eligible:
                    if (
                        "preview_closed" in context.issues
                        or "existing_financial_links" in context.issues
                    ):
                        raise ImportReviewClosed()
                    raise ImportRejected()
                records = session.scalars(
                    select(ImportRow)
                    .where(ImportRow.user_id == owner.user_id, ImportRow.import_job_id == identity)
                    .order_by(ImportRow.row_number, ImportRow.id)
                    .with_for_update()
                ).all()
                count = 0
                for row in records:
                    if row.selected:
                        session.add(
                            Transaction(
                                user_id=owner.user_id,
                                account_id=job.account_id,
                                category_id=row.suggested_category_id,
                                description=row.description,
                                amount=row.amount,
                                type=row.type,
                                status="posted",
                                effective_date=row.transaction_date,
                                import_row_id=row.id,
                            )
                        )
                        row.fingerprint = row_fingerprint(row)
                        row.selected = False
                        row.status = "imported"
                        count += 1
                    elif row.status in ("pending", "duplicate_candidate"):
                        row.status = "ignored"
                if count != context.selected_count:
                    raise ImportRejected()
                completed = datetime.now(UTC)
                result = ImportConfirmationReceipt(
                    **context.model_dump(
                        exclude={
                            "total_rows",
                            "selected_count",
                            "selected_rows",
                            "eligible",
                            "issues",
                            "matching_files",
                            "duplicates",
                            "receipt",
                            "etag",
                        }
                    ),
                    imported_rows=count,
                    not_imported_rows=len(records) - count,
                    completed_at=completed,
                )
                job.status = "completed"
                job.imported_rows = count
                job.completed_at = completed
                job.confirmation_key = key
                job.confirmation_hash = digest
                job.confirmation_result = result.model_dump(mode="json")
                session.flush()
        return result
