"""Upload contract, sensitive repr and SQL compilation without database access."""

import base64
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.schemas.imports import ImportInput, ImportSourceInput
from app.services.imports import ImportBusy, ImportRejected, job_query, source_bytes, upload_slot


def test_import_source_contract_hides_file_and_rejects_unsafe_metadata():
    encoded = base64.b64encode(b"Date;Description;Amount\n2026-01-02;Synthetic;1\n").decode()
    body = {"account_id": str(uuid4()), "filename": "synthetic.csv", "content_base64": encoded}
    source = ImportSourceInput(**body)
    assert source_bytes(source).startswith(b"Date;")
    assert encoded not in repr(source) and encoded not in source.model_dump_json()
    for extra in [
        {"filename": "C:private.csv"},
        {"filename": "../synthetic.csv"},
        {"filename": "C:\\private.csv"},
        {"filename": "private.csv\u202e"},
        {"filename": "not.pdf"},
        {"user_id": str(uuid4())},
        {"delimiter": "\t"},
    ]:
        with pytest.raises(ValidationError) as error:
            ImportSourceInput(**(body | extra))
        assert encoded not in str(error.value)
    with pytest.raises(ImportRejected):
        source_bytes(ImportSourceInput(**(body | {"content_base64": "not base64!"})))
    with pytest.raises(ValidationError):
        ImportInput(
            **body,
            mapping={
                "date_column": True,
                "description_column": 1,
                "amount_column": 2,
                "date_format": "iso",
                "money_format": "decimal-dot",
            },
        )
    query = str(job_query(uuid4()).compile(dialect=postgresql.dialect()))
    assert "import_jobs_1" in query and "invalid_rows" in query and "matching_files" in query
    with upload_slot(), upload_slot():
        with pytest.raises(ImportBusy):
            with upload_slot():
                raise AssertionError("Unreachable")
    with upload_slot():
        pass
