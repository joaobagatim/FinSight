"""Cookie-authenticated account endpoints; client input never selects an owner."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import SecretStr

from app.api.dependencies import get_current_user, get_session_service
from app.api.session_auth import SessionRequest, security
from app.core.auth_cookies import AuthCookies
from app.core.csrf import CsrfRejected
from app.schemas.accounts import (
    AccountCreatedResponse,
    AccountInput,
    AccountListResponse,
    AccountResponse,
)
from app.services.accounts import AccountService
from app.services.session_types import AuthContext
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


def account_service(service: Annotated[SessionService, Depends(get_session_service)]):
    return AccountService(service)


def account_access(
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


@router.post("", status_code=201, response_model=AccountCreatedResponse)
def create_account(
    data: AccountInput,
    key: Annotated[UUID, Depends(creation_key)],
    context: Annotated[SessionRequest, Depends(security)],
    user: Annotated[AuthContext, Depends(get_current_user)],
    service: Annotated[AccountService, Depends(account_service)],
    response: Response,
):
    if context.binding() != user.session_id:
        raise CsrfRejected()
    context.verify(user.session_id)
    account_id = service.create(context.values["access"], key, data)
    response.headers["Location"] = f"/api/v1/accounts/{account_id}"
    return AccountCreatedResponse(id=account_id)


@router.get("", response_model=AccountListResponse)
def list_accounts(
    token: Annotated[SecretStr, Depends(account_access)],
    service: Annotated[AccountService, Depends(account_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    return service.list(token, limit=limit, offset=offset)


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: UUID,
    token: Annotated[SecretStr, Depends(account_access)],
    service: Annotated[AccountService, Depends(account_service)],
):
    return service.get(token, account_id)
