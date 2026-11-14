"""Bounded advisory matching of current owned data; never delete or select records."""

import hashlib
import json
import unicodedata
from collections import Counter

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.models import ImportJob, ImportRow, Transaction
from app.schemas.import_duplicates import DuplicateItem, DuplicateReport
from app.services.imports import ImportNotFound, ImportRejected

MAX_SOURCE_ROWS = 5000
MAX_CANDIDATES = 10000
REVIEWABLE = ("pending", "duplicate_candidate", "imported")


def fingerprint(account, day, amount, kind, description):
    if day is None or amount is None or amount <= 0 or kind not in ("income", "expense"):
        return None
    normalized = " ".join(unicodedata.normalize("NFKC", description or "").casefold().split())
    if not normalized:
        return None
    canonical = json.dumps([str(account), day.isoformat(), format(amount, ".2f"), kind, normalized])
    return hashlib.sha256(canonical.encode()).hexdigest()


def row_fingerprint(row):
    if row.status not in REVIEWABLE or row.error_message:
        return None
    return fingerprint(row.account_id, row.transaction_date, row.amount, row.type, row.description)


class ImportDuplicateService:
    def __init__(self, sessions):
        self.sessions = sessions

    def report(self, token, identity):
        # Coordinate the short read with the same owner lock used by financial/review mutations.
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            job = session.scalar(
                select(ImportJob).where(
                    ImportJob.id == identity, ImportJob.user_id == owner.user_id
                )
            )
            if job is None:
                raise ImportNotFound()
            rows = session.scalars(
                select(ImportRow)
                .where(ImportRow.import_job_id == identity, ImportRow.user_id == owner.user_id)
                .order_by(ImportRow.row_number, ImportRow.id)
                .limit(MAX_SOURCE_ROWS + 1)
            ).all()
            if len(rows) > MAX_SOURCE_ROWS:
                raise ImportRejected()
            usable = [row for row in rows if row_fingerprint(row) is not None]
            own_prints = Counter(row_fingerprint(row) for row in usable)
            own_ids = Counter(row.external_id for row in usable if row.external_id)
            references = list(own_ids)
            dates = [row.transaction_date for row in rows if row.transaction_date is not None]
            start, end = (min(dates), max(dates)) if dates else (None, None)
            other_prints, other_ids = set(), set()
            tx_prints, tx_ids = Counter(), Counter()
            linked_prints, linked_ids = {}, {}
            limited = False
            overlap = False
            if usable:
                candidates = session.scalars(
                    select(ImportRow)
                    .join(
                        ImportJob,
                        (ImportJob.id == ImportRow.import_job_id)
                        & (ImportJob.user_id == ImportRow.user_id)
                        & (ImportJob.account_id == ImportRow.account_id),
                    )
                    .where(
                        ImportRow.user_id == owner.user_id,
                        ImportRow.account_id == job.account_id,
                        ImportRow.import_job_id != identity,
                        ImportJob.status.in_(("review", "completed")),
                        ImportRow.status.in_(REVIEWABLE),
                        or_(
                            ImportRow.transaction_date.between(start, end),
                            ImportRow.external_id.in_(references),
                        ),
                    )
                    .order_by(ImportRow.id)
                    .limit(MAX_CANDIDATES + 1)
                ).all()
                limited = len(candidates) > MAX_CANDIDATES
                for row in candidates[:MAX_CANDIDATES]:
                    key = row_fingerprint(row)
                    if key is not None:
                        other_prints.add(key)
                        if row.external_id:
                            other_ids.add(row.external_id)
                source = aliased(ImportRow)
                transactions = session.execute(
                    select(Transaction, source.external_id)
                    .outerjoin(
                        source,
                        (source.id == Transaction.import_row_id)
                        & (source.user_id == Transaction.user_id)
                        & (source.account_id == Transaction.account_id),
                    )
                    .where(
                        Transaction.user_id == owner.user_id,
                        Transaction.account_id == job.account_id,
                        Transaction.deleted_at.is_(None),
                        or_(
                            Transaction.effective_date.between(start, end),
                            source.external_id.in_(references),
                        ),
                    )
                    .order_by(Transaction.id)
                    .limit(MAX_CANDIDATES + 1)
                ).all()
                limited = limited or len(transactions) > MAX_CANDIDATES
                for transaction, external_id in transactions[:MAX_CANDIDATES]:
                    key = fingerprint(
                        job.account_id,
                        transaction.effective_date,
                        transaction.amount,
                        transaction.type,
                        transaction.description,
                    )
                    tx_prints[key] += 1
                    if external_id:
                        tx_ids[external_id] += 1
                    if transaction.import_row_id is not None:
                        linked_prints[transaction.import_row_id] = key
                        linked_ids[transaction.import_row_id] = external_id
            if dates:
                overlap = (
                    session.scalar(
                        select(ImportJob.id)
                        .join(
                            ImportRow,
                            (ImportRow.import_job_id == ImportJob.id)
                            & (ImportRow.user_id == ImportJob.user_id)
                            & (ImportRow.account_id == ImportJob.account_id),
                        )
                        .where(
                            ImportJob.user_id == owner.user_id,
                            ImportJob.account_id == job.account_id,
                            ImportJob.id != identity,
                            ImportJob.status.in_(("review", "completed")),
                        )
                        .group_by(ImportJob.id)
                        .having(
                            func.min(ImportRow.transaction_date) <= end,
                            func.max(ImportRow.transaction_date) >= start,
                        )
                        .limit(1)
                    )
                    is not None
                )
            items = []
            for row in usable:
                key = row_fingerprint(row)
                external = row.external_id
                reasons = []
                if own_prints[key] > 1:
                    reasons.append("same_preview_fingerprint")
                if external and own_ids[external] > 1:
                    reasons.append("same_preview_external_id")
                if key in other_prints:
                    reasons.append("other_preview_fingerprint")
                if external and external in other_ids:
                    reasons.append("other_preview_external_id")
                if tx_prints[key] > int(linked_prints.get(row.id) == key):
                    reasons.append("transaction_fingerprint")
                if external and tx_ids[external] > int(linked_ids.get(row.id) == external):
                    reasons.append("transaction_external_id")
                if reasons:
                    items.append(
                        DuplicateItem(row_id=row.id, row_number=row.row_number, reasons=reasons)
                    )
            result = DuplicateReport(
                job_id=job.id,
                checked_rows=len(usable),
                unchecked_rows=len(rows) - len(usable),
                period_start=start,
                period_end=end,
                overlapping_period=overlap,
                scan_limited=limited,
                candidate_limit=MAX_CANDIDATES,
                items=items,
            )
        return result
