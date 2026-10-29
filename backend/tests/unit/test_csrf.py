"""CSRF purpose/binding, cookie-header pairing and explicit origin checks."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.csrf import CsrfConfigurationError, CsrfRejected, CsrfService


@pytest.fixture
def service():
    return CsrfService(
        Settings(
            _env_file=None,
            auth_csrf_signing_key="ab" * 32,
            auth_allowed_origins=["http://localhost:5173", "https://app.example.test"],
        )
    )


@pytest.mark.parametrize("purpose", ["preauth", "session"])
def test_round_trip_and_random_nonce(service, purpose):
    binding = service.new_preauth_context() if purpose == "preauth" else uuid4()
    first = service.issue(purpose, binding)
    second = service.issue(purpose, binding)
    assert first != second
    assert isinstance(first, SecretStr)
    assert str(binding) not in first.get_secret_value()
    service.verify(first, first, purpose=purpose, binding=binding)


def test_missing_key_fails_closed():
    with pytest.raises(CsrfConfigurationError):
        CsrfService(Settings(_env_file=None))


@pytest.mark.parametrize("origin", ["http://localhost:5173", "https://app.example.test"])
def test_explicit_origin_allowed(service, origin):
    service.check_origin(origin)


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "",
        "https://evil.example.test",
        "http://localhost:5174",
        "http://localhost:5173/",
        " http://localhost:5173",
        "http://localhost:5173/path",
        "http://localhost:5173?x=1",
        "http://localhost:5173#x",
        "http://u:p@localhost:5173",
        "http:\\localhost:5173",
        "http://LOCALHOST:5173",
        "https://app.example.test.evil.test",
        "http://localhost:5173\n",
        "x" * 3000,
        "https://\u2603.test",
    ],
    ids=[f"origin-{i}" for i in range(17)],
)
def test_origin_rejected(service, origin):
    with pytest.raises(CsrfRejected, match="^CSRF verification failed$"):
        service.check_origin(origin)


def test_empty_origin_allowlist_denies():
    service = CsrfService(Settings(_env_file=None, auth_csrf_signing_key="ab" * 32))
    with pytest.raises(CsrfRejected):
        service.check_origin("http://localhost:5173")


@pytest.mark.parametrize(
    "value",
    [None, 7, "", "x" * 100000, "\u2603", "v1.0.a.b"],
    ids=["none", "int", "empty", "large", "unicode", "malformed"],
)
def test_invalid_inputs_do_not_echo(service, value, caplog):
    with pytest.raises(CsrfRejected) as caught:
        service.verify(value, value, purpose="session", binding=uuid4())
    assert str(caught.value) == "CSRF verification failed"
    assert not caplog.text


def test_signature_binding_purpose_and_pairing(service):
    binding = uuid4()
    token = service.issue("session", binding)
    other = service.issue("session", binding)
    for cookie, header, purpose, target in [
        (token, other, "session", binding),
        (token, token, "session", uuid4()),
        (token, token, "preauth", service.new_preauth_context()),
        (token, token, "invalid", binding),
    ]:
        with pytest.raises(CsrfRejected):
            service.verify(cookie, header, purpose=purpose, binding=target)
    raw = token.get_secret_value()
    tampered = raw[:-2] + ("A" if raw[-2] != "A" else "B") + raw[-1]
    with pytest.raises(CsrfRejected):
        service.verify(tampered, tampered, purpose="session", binding=binding)


def test_expiry_boundary_and_future_window():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    settings = Settings(_env_file=None, auth_csrf_signing_key="ab" * 32)
    service = CsrfService(settings, clock=lambda: now)
    binding = uuid4()
    token = service.issue("session", binding)
    now += timedelta(seconds=899)
    service.verify(token, token, purpose="session", binding=binding)
    now += timedelta(seconds=1)
    with pytest.raises(CsrfRejected):
        service.verify(token, token, purpose="session", binding=binding)
    now -= timedelta(seconds=901)
    with pytest.raises(CsrfRejected):
        service.verify(token, token, purpose="session", binding=binding)


@pytest.mark.parametrize(
    "purpose,binding",
    [("session", "client-id"), ("preauth", uuid4()), ("preauth", SecretStr("malformed"))],
)
def test_invalid_context_rejected(service, purpose, binding):
    with pytest.raises(CsrfRejected):
        service.issue(purpose, binding)


def test_naive_clock_rejected():
    service = CsrfService(
        Settings(_env_file=None, auth_csrf_signing_key="ab" * 32),
        clock=lambda: datetime(2026, 1, 1),
    )
    with pytest.raises(CsrfConfigurationError):
        service.issue("session", uuid4())
