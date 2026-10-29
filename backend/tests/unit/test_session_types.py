"""Session credentials cannot accidentally escape via normal serialization."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.services.session_types import AuthContext, SessionGrant


def test_grant_exports_only_context_and_expiry():
    now = datetime.now(UTC)
    context = AuthContext(
        user_id=uuid4(),
        session_id=uuid4(),
        name="Synthetic",
        email="owner@example.test",
        session_expires_at=now + timedelta(days=7),
    )
    grant = SessionGrant(
        context=context,
        access_token=SecretStr("synthetic-access-marker"),
        refresh_token=SecretStr("synthetic-refresh-marker"),
        access_expires_at=now,
    )
    for output in (repr(grant), str(grant.model_dump()), grant.model_dump_json()):
        assert "synthetic-access-marker" not in output
        assert "synthetic-refresh-marker" not in output
        assert "access_token" not in output
        assert "refresh_token" not in output
    assert grant.access_token.get_secret_value() == "synthetic-access-marker"
    with pytest.raises(ValidationError):
        grant.context = context
    with pytest.raises(ValidationError):
        context.user_id = uuid4()
