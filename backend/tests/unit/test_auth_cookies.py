"""Cookie scope, expiration, local exception and ambiguous input handling."""

from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from uuid import uuid4

import pytest
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response

from app.core.auth_cookies import AuthCookies, CookiePolicyRejected
from app.core.config import Settings
from app.services.session_types import AuthContext, SessionGrant


def request(*, scheme="https", host="app.example.test", peer="192.0.2.1", headers=()):
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "path": "/",
            "query_string": b"",
            "server": (host, 443),
            "client": (peer, 1234),
            "headers": [(b"host", host.encode()), *headers],
        }
    )


def cookies(response):
    result = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        result.load(header)
    return result


def grant(now):
    return SessionGrant(
        context=AuthContext(
            user_id=uuid4(),
            session_id=uuid4(),
            name="Synthetic",
            email="owner@example.test",
            session_expires_at=now + timedelta(days=7),
        ),
        access_token=SecretStr("synthetic-access"),
        refresh_token=SecretStr("synthetic-refresh"),
        access_expires_at=now + timedelta(seconds=900),
    )


def test_secure_flags_and_expiry():
    now = datetime.now(UTC)
    policy = AuthCookies(Settings(_env_file=None), request(), clock=lambda: now)
    response = Response()
    policy.set_grant(response, grant(now))
    policy.set_csrf(response, SecretStr("synthetic-csrf"), expires_at=now + timedelta(seconds=900))
    policy.set_preauth(
        response, SecretStr("synthetic-context"), expires_at=now + timedelta(seconds=900)
    )
    values = cookies(response)
    assert len(values) == 4
    for kind in ("access", "refresh", "csrf", "preauth"):
        item = values[policy.name(kind)]
        assert item["secure"]
        assert bool(item["httponly"]) == (kind != "csrf")
        assert item["samesite"] == "lax"
        assert item["path"] == "/"
        assert item["domain"] == ""
    assert values[policy.name("access")]["max-age"] == "900"
    assert values[policy.name("refresh")]["max-age"] == "604800"


def test_access_cookie_capped_by_absolute_session_expiry():
    now = datetime.now(UTC)
    data = grant(now)
    data = data.model_copy(
        update={
            "context": data.context.model_copy(
                update={"session_expires_at": now + timedelta(seconds=30)}
            )
        }
    )
    policy = AuthCookies(Settings(_env_file=None), request(), clock=lambda: now)
    response = Response()
    policy.set_grant(response, data)
    assert cookies(response)[policy.name("access")]["max-age"] == "30"


@pytest.mark.parametrize(
    "host,peer", [("localhost", "127.0.0.1"), ("127.0.0.1", "127.0.0.1"), ("[::1]", "::1")]
)
def test_local_http_requires_explicit_configuration(host, peer):
    policy = AuthCookies(
        Settings(_env_file=None, auth_cookie_secure=False),
        request(scheme="http", host=host, peer=peer),
    )
    assert policy.name("access") == "finsight_access"
    response = Response()
    policy.set_grant(response, grant(datetime.now(UTC)))
    assert not cookies(response)["finsight_access"]["secure"]


@pytest.mark.parametrize(
    "secure,scheme,host,peer",
    [
        (True, "http", "localhost", "127.0.0.1"),
        (False, "http", "localhost", "192.0.2.1"),
        (False, "http", "evil.test", "127.0.0.1"),
        (False, "http", "localhost", "not-an-ip"),
    ],
)
def test_insecure_or_spoofed_requests_rejected(secure, scheme, host, peer):
    with pytest.raises(CookiePolicyRejected):
        AuthCookies(
            Settings(_env_file=None, auth_cookie_secure=secure),
            request(scheme=scheme, host=host, peer=peer),
        )


def test_clear_uses_exact_scope_and_flags():
    policy = AuthCookies(Settings(_env_file=None), request())
    response = Response()
    policy.clear(response)
    values = cookies(response)
    assert len(values) == 4
    for kind in ("access", "refresh", "csrf", "preauth"):
        item = values[policy.name(kind)]
        assert item["max-age"] == "0"
        assert item["secure"]
        assert item["path"] == "/"
        assert item["domain"] == ""
        assert bool(item["httponly"]) == (kind != "csrf")


@pytest.mark.parametrize(
    "headers",
    [
        [(b"cookie", b"__Host-finsight-access=a; __Host-finsight-access=b")],
        [(b"cookie", b"__Host-finsight-access=a"), (b"cookie", b"__Host-finsight-access=a")],
        [(b"cookie", b"__Host-finsight-refresh=")],
        [(b"cookie", b'__Host-finsight-access="quoted"')],
        [(b"cookie", b"__Host-finsight-access=a\r\nb")],
        [(b"cookie", b"unrelated=\xff")],
        [(b"cookie", b"x=" + b"a" * 17000)],
        [(b"cookie", b"__Host-finsight-access=" + b"a" * 4097)],
    ],
    ids=[f"bad-cookie-{i}" for i in range(8)],
)
def test_ambiguous_or_oversized_input_rejected(headers):
    policy = AuthCookies(Settings(_env_file=None), request(headers=headers))
    with pytest.raises(CookiePolicyRejected):
        policy.read()


def test_read_secret_values_ignores_unrelated_cookie():
    policy = AuthCookies(
        Settings(_env_file=None),
        request(headers=[(b"cookie", b"unrelated=ok; __Host-finsight-access=synthetic-marker")]),
    )
    result = policy.read()
    assert result["access"].get_secret_value() == "synthetic-marker"
    assert "synthetic-marker" not in repr(result)


def test_expired_and_overlong_context_deadlines_rejected():
    now = datetime.now(UTC)
    policy = AuthCookies(Settings(_env_file=None), request(), clock=lambda: now)
    response = Response()
    with pytest.raises(CookiePolicyRejected):
        policy.set_grant(response, grant(now - timedelta(seconds=900)))
    assert "set-cookie" not in response.headers
    for setter in (policy.set_csrf, policy.set_preauth):
        for seconds in (0, -1, 901):
            with pytest.raises(CookiePolicyRejected):
                setter(
                    response, SecretStr("synthetic"), expires_at=now + timedelta(seconds=seconds)
                )


@pytest.mark.parametrize(
    "value",
    ["a;b", 'a"b', "a\\b", "\u2603", "a\nb", "x" * 4097],
    ids=["semicolon", "quote", "slash", "unicode", "newline", "large"],
)
def test_unsafe_output_rejected(value):
    now = datetime.now(UTC)
    policy = AuthCookies(Settings(_env_file=None), request(), clock=lambda: now)
    with pytest.raises(CookiePolicyRejected):
        policy.set_csrf(Response(), SecretStr(value), expires_at=now + timedelta(seconds=60))


def test_bad_second_credential_does_not_write_partial_cookies():
    now = datetime.now(UTC)
    policy = AuthCookies(Settings(_env_file=None), request(), clock=lambda: now)
    data = grant(now).model_copy(update={"refresh_token": SecretStr("bad;token")})
    response = Response()
    with pytest.raises(CookiePolicyRejected):
        policy.set_grant(response, data)
    assert "set-cookie" not in response.headers


def test_naive_deadlines_fail_with_uniform_error():
    now = datetime.now(UTC)
    policy = AuthCookies(Settings(_env_file=None), request(), clock=lambda: now)
    for setter in (policy.set_csrf, policy.set_preauth):
        with pytest.raises(CookiePolicyRejected):
            setter(Response(), SecretStr("synthetic"), expires_at=datetime(2026, 1, 1))
    with pytest.raises(CookiePolicyRejected):
        policy.set_grant(
            Response(), grant(now).model_copy(update={"access_expires_at": datetime(2026, 1, 1)})
        )


def test_selective_clear_preserves_other_cookie_names():
    policy = AuthCookies(Settings(_env_file=None), request())
    response = Response()
    policy.clear(response, kinds=("preauth",))
    assert set(cookies(response)) == {"__Host-finsight-preauth"}
