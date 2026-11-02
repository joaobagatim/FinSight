"""Shared cookie access, CSRF mutation checks and idempotency-key parsing."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from pydantic import SecretStr

from app.api.dependencies import get_current_user
from app.api.session_auth import SessionRequest, security
from app.core.auth_cookies import AuthCookies
from app.core.csrf import CsrfRejected
from app.services.session_types import AuthContext


def financial_access(
    request: Request, _user: Annotated[AuthContext, Depends(get_current_user)]
) -> SecretStr:
    return AuthCookies(request.app.state.settings, request).read()["access"]


def creation_key(
    value: Annotated[str, Header(alias="Idempotency-Key", min_length=36, max_length=36)],
) -> UUID:
    try:
        key = UUID(value)
    except ValueError:
        raise HTTPException(422, "Invalid idempotency key") from None
    if key.version != 4 or str(key) != value.lower():
        raise HTTPException(422, "Invalid idempotency key")
    return key


def financial_mutation(
    context: Annotated[SessionRequest, Depends(security)],
    user: Annotated[AuthContext, Depends(get_current_user)],
) -> SecretStr:
    if context.binding() != user.session_id:
        raise CsrfRejected()
    context.verify(user.session_id)
    return context.values["access"]
