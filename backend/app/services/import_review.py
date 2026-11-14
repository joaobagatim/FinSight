"""Conditional owned preview review, explicitly separated from financial posting."""

import hashlib
import hmac
import json

from sqlalchemy import select

from app.models import Account, Category, ImportJob, ImportRow, Transaction
from app.schemas.imports import ImportRowResponse
from app.services.imports import ImportNotFound, ImportRejected


class ImportReviewStale(Exception):
    pass


class ImportReviewClosed(Exception):
    pass


def review_query(owner, job_id):
    linked = (
        select(Transaction.id)
        .where(Transaction.user_id == owner, Transaction.import_row_id == ImportRow.id)
        .correlate(ImportRow)
        .exists()
    )
    return (
        select(
            ImportRow,
            ImportJob.status.label("job_status"),
            Account.is_active.label("account_active"),
            Account.opening_date,
            Category.name.label("category_name"),
            Category.is_active.label("category_active"),
            Category.type.label("category_type"),
            linked.label("linked"),
        )
        .join(
            ImportJob,
            (ImportJob.id == ImportRow.import_job_id)
            & (ImportJob.user_id == ImportRow.user_id)
            & (ImportJob.account_id == ImportRow.account_id),
        )
        .join(
            Account, (Account.id == ImportRow.account_id) & (Account.user_id == ImportRow.user_id)
        )
        .outerjoin(
            Category,
            (Category.id == ImportRow.suggested_category_id)
            & (Category.user_id == ImportRow.user_id),
        )
        .where(ImportRow.user_id == owner, ImportRow.import_job_id == job_id)
    )


def review_response(context):
    row = context.ImportRow
    open_review = context.job_status == "review" and row.status != "imported" and not context.linked
    core_valid = (
        row.transaction_date is not None
        and row.transaction_date > context.opening_date
        and bool(row.description and row.description.strip())
        and row.amount is not None
        and row.amount > 0
        and row.type in ("income", "expense")
        and row.status in ("pending", "duplicate_candidate")
        and not row.error_message
    )
    problems = []
    if not open_review:
        problems.append("review_closed")
    if not context.account_active:
        problems.append("account_archived")
    if not core_valid:
        problems.append("record_invalid")
    if row.suggested_category_id is None:
        problems.append("category_required")
    elif not context.category_active:
        problems.append("category_unavailable")
    elif context.category_type != row.type:
        problems.append("category_type_mismatch")
    result = ImportRowResponse(
        id=row.id,
        row_number=row.row_number,
        transaction_date=row.transaction_date,
        description=row.description,
        amount=row.amount,
        type=row.type,
        external_id=row.external_id,
        status=row.status,
        error_codes=row.error_message.split(",") if row.error_message else [],
        selected=row.selected,
        category_id=row.suggested_category_id,
        category_name=context.category_name,
        editable=open_review and context.account_active,
        selection_editable=open_review,
        selection_eligible=not problems,
        review_errors=problems,
    )
    canonical = json.dumps(
        result.model_dump(mode="json", exclude={"etag"}), sort_keys=True, separators=(",", ":")
    )
    result.etag = '"' + hashlib.sha256(canonical.encode()).hexdigest() + '"'
    return result


class ImportReviewService:
    def __init__(self, sessions):
        self.sessions = sessions

    def get(self, token, job_id, row_id):
        with self.sessions.authorized_transaction(token) as (session, owner):
            context = session.execute(
                review_query(owner.user_id, job_id).where(ImportRow.id == row_id)
            ).one_or_none()
            if context is None:
                raise ImportNotFound()
            result = review_response(context)
        return result

    @staticmethod
    def locked(session, owner, job_id, row_id, etag):
        job = session.scalar(
            select(ImportJob)
            .where(ImportJob.id == job_id, ImportJob.user_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise ImportNotFound()
        row = session.scalar(
            select(ImportRow)
            .where(
                ImportRow.id == row_id,
                ImportRow.import_job_id == job_id,
                ImportRow.user_id == owner,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ImportNotFound()
        context = session.execute(review_query(owner, job_id).where(ImportRow.id == row_id)).one()
        current = review_response(context)
        if not hmac.compare_digest(current.etag, etag):
            raise ImportReviewStale()
        if not current.selection_editable:
            raise ImportReviewClosed()
        return row, context, current

    def edit(self, token, job_id, row_id, data, etag):
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row, context, current = self.locked(session, owner.user_id, job_id, row_id, etag)
            if not current.editable or data.transaction_date <= context.opening_date:
                raise ImportRejected()
            if data.category_id is not None:
                category = session.scalar(
                    select(Category)
                    .where(Category.id == data.category_id, Category.user_id == owner.user_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if category is None or not category.is_active or category.type != data.type:
                    raise ImportRejected()
            row.selected = False
            row.transaction_date = data.transaction_date
            row.description = data.description
            row.amount = data.amount
            row.type = data.type
            row.suggested_category_id = data.category_id
            row.status = "pending"
            row.error_message = None
            row.fingerprint = None
            session.flush()
            result = review_response(
                session.execute(
                    review_query(owner.user_id, job_id).where(ImportRow.id == row_id)
                ).one()
            )
        return result

    def select(self, token, job_id, row_id, data, etag):
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row, _, current = self.locked(session, owner.user_id, job_id, row_id, etag)
            if data.selected and not current.selection_eligible:
                raise ImportRejected()
            row.selected = data.selected
            session.flush()
            result = review_response(
                session.execute(
                    review_query(owner.user_id, job_id).where(ImportRow.id == row_id)
                ).one()
            )
        return result
