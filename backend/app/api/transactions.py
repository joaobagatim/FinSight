"""Manual financial movements; imports, edits and deletion are separate flows."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import creation_key
from app.api.financial_auth import financial_access as account_access
from app.api.financial_auth import financial_mutation as category_mutation
from app.schemas.transactions import (
    AccountBalanceResponse,
    TransactionCreatedResponse,
    TransactionInput,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.sessions import SessionService
from app.services.transactions import TransactionService

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])
balance_router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


def transaction_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return TransactionService(sessions)


@router.post("", status_code=201, response_model=TransactionCreatedResponse)
def create_transaction(
    data: TransactionInput,
    response: Response,
    token: Annotated[SecretStr, Depends(category_mutation)],
    key: Annotated[UUID, Depends(creation_key)],
    service: Annotated[TransactionService, Depends(transaction_service)],
):
    transaction_id = service.create(token, key, data)
    response.headers["Location"] = f"/api/v1/transactions/{transaction_id}"
    return TransactionCreatedResponse(id=transaction_id)


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    token: Annotated[SecretStr, Depends(account_access)],
    service: Annotated[TransactionService, Depends(transaction_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    type: Literal["income", "expense"] | None = None,
    status: Literal["planned", "posted"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    return service.list(
        token,
        limit=limit,
        offset=offset,
        account_id=account_id,
        category_id=category_id,
        kind=type,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: UUID,
    token: Annotated[SecretStr, Depends(account_access)],
    service: Annotated[TransactionService, Depends(transaction_service)],
):
    return service.get(token, transaction_id)


@balance_router.get("/{account_id}/balance", response_model=AccountBalanceResponse)
def get_balance(
    account_id: UUID,
    as_of: date,
    token: Annotated[SecretStr, Depends(account_access)],
    service: Annotated[TransactionService, Depends(transaction_service)],
):
    return service.balance(token, account_id, as_of)
