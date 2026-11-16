"""Owned CSV inspection and atomic preview storage; never create transactions here."""

import base64
import binascii
import hashlib
import hmac
import json
from contextlib import contextmanager
from threading import BoundedSemaphore
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.imports.csv_parser import MAX_BYTES, normalize_rows, read_csv
from app.models import Account, ImportCreationRequest, ImportJob, ImportRow
from app.schemas.imports import (
    ImportInput,
    ImportInspectionResponse,
    ImportJobResponse,
    ImportListResponse,
    ImportRowsResponse,
    ImportSourceInput,
)
from app.services.sessions import SessionService


class ImportNotFound(Exception):
    pass


class ImportRejected(Exception):
    pass


class ImportConflict(Exception):
    pass


class ImportBusy(Exception):
    pass


_CSV_SLOTS = BoundedSemaphore(2)


@contextmanager
def upload_slot():
    if not _CSV_SLOTS.acquire(blocking=False):
        raise ImportBusy()
    try:
        yield
    finally:
        _CSV_SLOTS.release()


def source_bytes(data: ImportSourceInput) -> bytes:
    try:
        source = base64.b64decode(data.content_base64.get_secret_value(), validate=True)
    except (ValueError, binascii.Error):
        raise ImportRejected() from None
    if not source or len(source) > MAX_BYTES:
        raise ImportRejected()
    return source


def matching_query(owner, account_id, checksum, *, excluded_id=None):
    job = aliased(ImportJob)
    query = (
        select(func.count())
        .select_from(job)
        .where(job.user_id == owner, job.account_id == account_id, job.file_checksum == checksum)
    )
    if excluded_id is not None:
        query = query.where(job.id != excluded_id)
    return query


def job_query(owner):
    invalid = (
        select(func.count())
        .select_from(ImportRow)
        .where(
            ImportRow.user_id == owner,
            ImportRow.import_job_id == ImportJob.id,
            ImportRow.status == "invalid",
        )
        .correlate(ImportJob)
        .scalar_subquery()
    )
    matching = (
        matching_query(
            owner, ImportJob.account_id, ImportJob.file_checksum, excluded_id=ImportJob.id
        )
        .correlate(ImportJob)
        .scalar_subquery()
    )
    selected = (
        select(func.count())
        .select_from(ImportRow)
        .where(
            ImportRow.user_id == owner,
            ImportRow.import_job_id == ImportJob.id,
            ImportRow.selected.is_(True),
        )
        .correlate(ImportJob)
        .scalar_subquery()
    )
    return select(
        ImportJob,
        invalid.label("invalid_rows"),
        matching.label("matching_files"),
        selected.label("selected_rows"),
    ).where(ImportJob.user_id == owner)


def job_response(row):
    job = row.ImportJob
    return ImportJobResponse(
        id=job.id,
        account_id=job.account_id,
        filename=job.filename,
        status=job.status,
        total_rows=job.total_rows,
        imported_rows=job.imported_rows,
        invalid_rows=row.invalid_rows,
        matching_files=row.matching_files,
        selected_rows=row.selected_rows,
    )


class ImportService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    @staticmethod
    def account(session, owner, identity, *, lock=False):
        query = select(Account).where(Account.id == identity, Account.user_id == owner)
        account = session.scalar(query.with_for_update() if lock else query)
        if account is None:
            raise ImportNotFound()
        if not account.is_active or account.currency != "BRL":
            raise ImportRejected()
        return account

    def inspect(self, token: SecretStr, data: ImportSourceInput):
        with upload_slot(), self.sessions.authorized_transaction(token) as (session, owner):
            account = self.account(session, owner.user_id, data.account_id)
            document = read_csv(source_bytes(data), delimiter=data.delimiter)
            matches = session.scalar(matching_query(owner.user_id, account.id, document.checksum))
            result = ImportInspectionResponse(
                account_id=account.id,
                opening_date=account.opening_date,
                headers=list(document.headers),
                delimiter=document.delimiter,
                total_rows=len(document.rows),
                sample=[list(cells) for _, cells in document.rows[:5]],
                matching_files=matches,
            )
        return result

    def create(self, token: SecretStr, key: UUID, data: ImportInput):
        with (
            upload_slot(),
            self.sessions.authorized_transaction(token, lock=True) as (session, owner),
        ):
            source = source_bytes(data)
            checksum = hashlib.sha256(source).hexdigest()
            canonical = json.dumps(
                {
                    "account_id": str(data.account_id),
                    "filename": data.filename,
                    "checksum": checksum,
                    "delimiter": data.delimiter,
                    "mapping": data.mapping.model_dump(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(canonical.encode()).hexdigest()
            previous = session.get(ImportCreationRequest, (owner.user_id, key))
            if previous is not None:
                if not hmac.compare_digest(previous.request_hash, digest):
                    raise ImportConflict()
                identity = previous.import_job_id
            else:
                account = self.account(session, owner.user_id, data.account_id, lock=True)
                document = read_csv(source, delimiter=data.delimiter)
                rows = normalize_rows(
                    document, data.mapping.layout(), opening_date=account.opening_date
                )
                job = ImportJob(
                    user_id=owner.user_id,
                    account_id=account.id,
                    filename=data.filename,
                    file_type="csv",
                    file_checksum=checksum,
                    status="review",
                    total_rows=len(rows),
                    imported_rows=0,
                )
                session.add(job)
                session.flush()
                identity = job.id
                session.add_all(
                    [
                        ImportRow(
                            user_id=owner.user_id,
                            account_id=account.id,
                            import_job_id=identity,
                            row_number=row.row_number,
                            transaction_date=row.transaction_date,
                            description=row.description,
                            amount=row.amount,
                            type=row.type,
                            external_id=row.external_id,
                            status="pending" if row.valid else "invalid",
                            error_message=",".join(row.errors) or None,
                        )
                        for row in rows
                    ]
                )
                session.flush()
                session.add(
                    ImportCreationRequest(
                        user_id=owner.user_id,
                        idempotency_key=key,
                        request_hash=digest,
                        account_id=account.id,
                        import_job_id=identity,
                    )
                )
                session.flush()
        return identity

    def get(self, token: SecretStr, identity: UUID):
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.execute(
                job_query(owner.user_id).where(ImportJob.id == identity)
            ).one_or_none()
            if row is None:
                raise ImportNotFound()
            result = job_response(row)
        return result

    def list(self, token: SecretStr, *, limit: int, offset: int):
        with self.sessions.authorized_transaction(token) as (session, owner):
            rows = session.execute(
                job_query(owner.user_id)
                .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = ImportListResponse(
                items=[job_response(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result

    def rows(self, token: SecretStr, identity: UUID, *, limit: int, offset: int):
        from app.services.import_review import review_query, review_response

        with self.sessions.authorized_transaction(token) as (session, owner):
            if (
                session.scalar(
                    select(ImportJob.id).where(
                        ImportJob.id == identity, ImportJob.user_id == owner.user_id
                    )
                )
                is None
            ):
                raise ImportNotFound()
            rows = session.execute(
                review_query(owner.user_id, identity)
                .order_by(ImportRow.row_number, ImportRow.id)
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = ImportRowsResponse(
                items=[review_response(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result
