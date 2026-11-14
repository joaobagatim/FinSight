"""Confirmation accepts explicit acknowledgements only and binds the reviewed version."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.import_confirmation import ImportConfirmationInput
from app.services.import_confirmation import confirmation_digest


def test_confirmation_acknowledgements_are_strict_and_digest_binds_job_and_snapshot():
    body = {
        "acknowledge_duplicates": True,
        "acknowledge_classification": True,
        "acknowledge_reservations": True,
    }
    data = ImportConfirmationInput(**body)
    for changes in (
        {"acknowledge_duplicates": False},
        {"acknowledge_classification": 1},
        {"acknowledge_reservations": "true"},
        {"selected_rows": [str(uuid4())]},
        {"user_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            ImportConfirmationInput(**(body | changes))
    identity, version = uuid4(), '"' + "a" * 64 + '"'
    digest = confirmation_digest(identity, version, data)
    assert len(digest) == 64 and digest == confirmation_digest(identity, version, data)
    assert digest != confirmation_digest(uuid4(), version, data)
    assert digest != confirmation_digest(identity, '"' + "b" * 64 + '"', data)
