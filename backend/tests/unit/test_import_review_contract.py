"""Strict review inputs and context-sensitive tags without financial posting."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.models import ImportRow
from app.schemas.import_review import ImportRowEditInput, ImportSelectionInput
from app.services.import_review import review_query, review_response


def test_review_contract_selection_eligibility_and_tags_are_exact_and_private():
    body = {
        "transaction_date": "2026-01-02",
        "description": "Synthetic corrected row",
        "amount": "1234.56",
        "type": "expense",
    }
    assert ImportRowEditInput(**body).amount == Decimal("1234.56")
    for changes in [
        {"amount": 0.1},
        {"amount": "0"},
        {"description": "bad\u202e"},
        {"transaction_date": "2026-02-30"},
        {"user_id": str(uuid4())},
        {"selected": True},
    ]:
        with pytest.raises(ValidationError):
            ImportRowEditInput(**(body | changes))
    with pytest.raises(ValidationError):
        ImportSelectionInput(selected="true")
    row = ImportRow(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        import_job_id=uuid4(),
        row_number=2,
        transaction_date=date(2026, 1, 2),
        description="Synthetic corrected row",
        amount=Decimal("1234.56"),
        type="expense",
        status="pending",
        selected=False,
        error_message=None,
    )
    context = SimpleNamespace(
        ImportRow=row,
        job_status="review",
        account_active=True,
        opening_date=date(2026, 1, 1),
        category_name=None,
        category_active=None,
        category_type=None,
        linked=False,
    )
    first = review_response(context)
    assert (
        first.editable
        and not first.selection_eligible
        and first.review_errors == ["category_required"]
    )
    row.suggested_category_id = uuid4()
    context.category_name = "Synthetic expense"
    context.category_active = True
    context.category_type = "expense"
    ready = review_response(context)
    assert ready.selection_eligible and ready.etag != first.etag
    row.selected = True
    assert review_response(context).etag != ready.etag
    context.category_active = False
    assert not review_response(context).selection_eligible
    context.account_active = False
    assert not review_response(context).editable and review_response(context).selection_editable
    context.linked = True
    assert not review_response(context).selection_editable
    assert '"1234.56"' in first.model_dump_json()
    assert "EXISTS" in str(review_query(uuid4(), uuid4()).compile(dialect=postgresql.dialect()))
