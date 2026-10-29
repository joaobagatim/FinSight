"""Real JWT verification, strict claim policy, deterministic time and secret handling."""

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from pydantic import SecretStr

import app.core.tokens as tokens
from app.core.config import Settings
from app.core.tokens import (
    MAX_TOKEN_BYTES,
    AccessTokenService,
    InvalidAccessToken,
    TokenConfigurationError,
)

# Public deterministic fixtures, never used as application configuration.
SYNTHETIC_KEY = bytes(range(32))
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
TOKEN_ID = UUID("33333333-3333-4333-8333-333333333333")
VERSION1_UUID = UUID("11111111-1111-1111-8111-111111111111")


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            assert tz is not None
            return cls.current.astimezone(tz)

    monkeypatch.setattr(tokens, "datetime", Clock)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    return Clock


@pytest.fixture
def settings():
    return Settings(_env_file=None, jwt_signing_key=SYNTHETIC_KEY.hex())


@pytest.fixture
def service(settings):
    return AccessTokenService(settings)


@pytest.fixture
def payload(clock):
    now = int(clock.current.timestamp())
    return {
        "sub": str(USER_ID),
        "sid": str(SESSION_ID),
        "jti": str(TOKEN_ID),
        "iss": "finsight-api",
        "aud": "finsight-web",
        "token_use": "access",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
    }


def sign(payload):
    # Sign raw JSON to exercise invalid claims that jwt.encode refuses to issue.
    # Production continues to use the validated high-level encoder.
    return jwt.api_jws.encode(
        json.dumps(payload).encode("utf-8"),
        SYNTHETIC_KEY,
        algorithm="HS256",
        headers={"typ": "finsight-access+jwt"},
    )


def test_issue_and_verify_real_signature_and_minimal_claims(service, clock):
    encoded = service.issue(USER_ID, SESSION_ID)
    assert isinstance(encoded, SecretStr)
    decoded = jwt.decode(
        encoded.get_secret_value(),
        SYNTHETIC_KEY,
        algorithms=["HS256"],
        issuer="finsight-api",
        audience="finsight-web",
    )
    assert set(decoded) == {"sub", "sid", "jti", "iss", "aud", "token_use", "iat", "nbf", "exp"}
    assert decoded["exp"] - decoded["iat"] == 900
    assert decoded["nbf"] == decoded["iat"] == int(clock.current.timestamp())
    assert decoded["token_use"] == "access"
    assert UUID(decoded["jti"]).version == 4
    assert jwt.get_unverified_header(encoded.get_secret_value()) == {
        "alg": "HS256",
        "typ": "finsight-access+jwt",
    }
    claims = service.verify(encoded)
    assert claims.user_id == USER_ID
    assert claims.session_id == SESSION_ID
    assert str(claims.token_id) == decoded["jti"]
    assert claims.issued_at == claims.not_before == clock.current
    assert claims.expires_at == clock.current + timedelta(seconds=900)
    assert claims.issuer == "finsight-api" and claims.audience == "finsight-web"
    assert all(
        value.tzinfo is UTC for value in (claims.issued_at, claims.not_before, claims.expires_at)
    )


def test_fresh_token_ids_for_same_user_session_and_time(service, clock):
    first = service.issue(USER_ID, SESSION_ID)
    second = service.issue(USER_ID, SESSION_ID)
    assert first != second
    assert service.verify(first).token_id != service.verify(second).token_id


def test_missing_key_fails_closed_without_loading_environment():
    settings = Settings(_env_file=None)
    assert settings.jwt_signing_key is None
    with pytest.raises(TokenConfigurationError, match="^JWT signing key is not configured$"):
        AccessTokenService(settings)


def test_configured_shorter_lifetime_and_exact_expiry(clock):
    service = AccessTokenService(
        Settings(_env_file=None, jwt_signing_key=SYNTHETIC_KEY.hex(), jwt_access_ttl_seconds=60)
    )
    encoded = service.issue(USER_ID, SESSION_ID)
    assert service.verify(encoded).expires_at == clock.current + timedelta(seconds=60)
    clock.current += timedelta(seconds=59)
    service.verify(encoded)
    clock.current += timedelta(seconds=1)
    with pytest.raises(InvalidAccessToken, match="^Invalid access token$"):
        service.verify(encoded)


def test_issuer_and_audience_are_explicit_and_configurable(clock):
    service = AccessTokenService(
        Settings(
            _env_file=None,
            jwt_signing_key=SYNTHETIC_KEY.hex(),
            jwt_issuer="custom-api",
            jwt_audience="custom-web",
        )
    )
    claims = service.verify(service.issue(USER_ID, SESSION_ID))
    assert claims.issuer == "custom-api" and claims.audience == "custom-web"


@pytest.mark.parametrize("identifier", ["🔐" * 120, "é" * 120, "\x00" * 120])
def test_maximum_unicode_identifiers_produce_a_token_the_service_accepts(clock, identifier):
    service = AccessTokenService(
        Settings(
            _env_file=None,
            jwt_signing_key=SYNTHETIC_KEY.hex(),
            jwt_issuer=identifier,
            jwt_audience=identifier,
        )
    )
    encoded = service.issue(USER_ID, SESSION_ID)
    assert len(encoded.get_secret_value().encode("ascii")) <= MAX_TOKEN_BYTES
    claims = service.verify(encoded)
    assert claims.issuer == claims.audience == identifier


@pytest.mark.parametrize(
    "field", ["sub", "sid", "jti", "iss", "aud", "token_use", "iat", "nbf", "exp"]
)
def test_required_claims_cannot_be_omitted(service, payload, field):
    del payload[field]
    with pytest.raises(InvalidAccessToken):
        service.verify(sign(payload))


@pytest.mark.parametrize("field", ["sub", "sid", "jti"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        [],
        {},
        True,
        "invalid",
        "00000000-0000-0000-0000-000000000000",
        str(VERSION1_UUID),
        USER_ID.hex,
        str(USER_ID).upper().replace("1", "A", 1),
    ],
)
def test_identity_claims_require_canonical_uuid4(service, payload, field, value):
    payload[field] = value
    with pytest.raises(InvalidAccessToken):
        service.verify(sign(payload))


@pytest.mark.parametrize("field", ["iat", "nbf", "exp"])
@pytest.mark.parametrize(
    "value", [None, True, False, "1893553445", 1893553445.0, {}, [], float("inf"), float("nan")]
)
def test_numeric_dates_require_integers_not_coercible_values(service, payload, field, value):
    payload[field] = value
    with pytest.raises(InvalidAccessToken):
        service.verify(sign(payload))


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "untrusted-api"},
        {"iss": None},
        {"aud": "other-web"},
        {"aud": ["finsight-web"]},
        {"aud": ["finsight-web", "other"]},
        {"token_use": "refresh"},
        {"token_use": None},
        {"unexpected": "private-marker"},
        {"email": "synthetic@example.com"},
        {"password": "synthetic-private-marker"},
        {"user_id": str(USER_ID)},
    ],
)
def test_valid_signature_does_not_bypass_claim_policy(service, payload, changes):
    with pytest.raises(InvalidAccessToken):
        service.verify(sign(payload | changes))


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "future-iat",
        "future-nbf",
        "nbf-before-iat",
        "long-lived",
        "empty-lived",
        "reversed",
    ],
)
def test_time_policy_is_checked_after_signature(service, payload, clock, case):
    now = int(clock.current.timestamp())
    if case == "expired":
        payload.update(iat=now - 900, nbf=now - 900, exp=now)
    elif case == "future-iat":
        payload.update(iat=now + 1, nbf=now + 1, exp=now + 61)
    elif case == "future-nbf":
        payload["nbf"] = now + 1
    elif case == "nbf-before-iat":
        payload["nbf"] = now - 1
    elif case == "long-lived":
        payload["exp"] = now + 901
    elif case == "empty-lived":
        payload.update(iat=now - 1, nbf=now - 1, exp=now - 1)
    else:
        payload.update(iat=now - 1, nbf=now - 1, exp=now - 2)
    with pytest.raises(InvalidAccessToken):
        service.verify(sign(payload))


@pytest.mark.parametrize(
    "headers",
    [
        {"typ": "JWT"},
        {"typ": None},
        {"typ": "refresh+jwt"},
        {"typ": "finsight-access+jwt", "kid": "arbitrary"},
        {"typ": "finsight-access+jwt", "jku": "https://untrusted.example.test/keys"},
        {"typ": "finsight-access+jwt", "crit": ["unknown"]},
    ],
)
def test_signed_header_must_match_supported_access_format(service, payload, headers):
    encoded = jwt.encode(payload, SYNTHETIC_KEY, algorithm="HS256", headers=headers)
    with pytest.raises(InvalidAccessToken):
        service.verify(encoded)


@pytest.mark.parametrize("algorithm", ["none", "HS512"])
def test_header_cannot_select_another_algorithm(service, payload, algorithm):
    encoded = jwt.encode(
        payload,
        None if algorithm == "none" else bytes(range(64)),
        algorithm=algorithm,
        headers={"typ": "finsight-access+jwt"},
    )
    with pytest.raises(InvalidAccessToken):
        service.verify(encoded)


def test_wrong_signing_key_is_rejected(service, payload):
    encoded = jwt.encode(
        payload, SYNTHETIC_KEY[::-1], algorithm="HS256", headers={"typ": "finsight-access+jwt"}
    )
    with pytest.raises(InvalidAccessToken):
        service.verify(encoded)


@pytest.mark.parametrize("part", ["payload", "signature"])
def test_tampering_is_rejected(service, payload, part):
    header, body, signature = sign(payload).split(".")
    if part == "payload":
        altered = payload | {"sub": str(uuid4())}
        body = base64.urlsafe_b64encode(json.dumps(altered).encode()).rstrip(b"=").decode()
    else:
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(InvalidAccessToken):
        service.verify(".".join((header, body, signature)))


@pytest.mark.parametrize(
    "value", [None, 123, True, {}, [], b"invalid", "", "invalid", "a.b.c", "..", "á", "\ud800"]
)
def test_malformed_tokens_have_uniform_safe_errors(service, value, caplog):
    with pytest.raises(InvalidAccessToken) as error:
        service.verify(value)
    assert str(error.value) == "Invalid access token"
    assert error.value.__cause__ is None
    assert not caplog.text


def test_oversized_token_is_rejected_before_parsing(service, monkeypatch):
    def unexpected_parser(_value):
        pytest.fail("Oversized token reached the parser")

    monkeypatch.setattr(jwt, "get_unverified_header", unexpected_parser)
    with pytest.raises(InvalidAccessToken):
        service.verify("a" * (MAX_TOKEN_BYTES + 1))


def test_deeply_nested_untrusted_header_is_safe(service):
    header = base64.urlsafe_b64encode(b"[" * 1100 + b"0" + b"]" * 1100).rstrip(b"=").decode()
    encoded = header + ".e30.signature"
    assert len(encoded) < MAX_TOKEN_BYTES
    with pytest.raises(InvalidAccessToken, match="^Invalid access token$"):
        service.verify(encoded)


def test_keys_and_tokens_are_absent_from_representations_or_errors(
    service, payload, clock, settings, caplog
):
    token = service.issue(USER_ID, SESSION_ID)
    raw = token.get_secret_value()
    assert raw not in repr(token)
    assert SYNTHETIC_KEY.hex() not in repr(service) + repr(settings) + settings.model_dump_json()
    assert "jwt_signing_key" not in settings.model_dump()
    payload["unexpected"] = "sensitive-marker"
    bad = sign(payload)
    with pytest.raises(InvalidAccessToken) as error:
        service.verify(bad)
    assert bad not in str(error.value) + repr(error.value) + caplog.text
    assert "sensitive-marker" not in str(error.value) + caplog.text
    assert raw not in repr(service.verify(token))


@pytest.mark.parametrize("value", [None, "invalid", str(USER_ID), VERSION1_UUID, UUID(int=0)])
@pytest.mark.parametrize("field", ["user_id", "session_id"])
def test_issuance_requires_server_supplied_uuid4_objects(service, clock, field, value):
    with pytest.raises(ValueError, match="^User and session IDs must be UUIDv4$"):
        service.issue(**({"user_id": USER_ID, "session_id": SESSION_ID} | {field: value}))
