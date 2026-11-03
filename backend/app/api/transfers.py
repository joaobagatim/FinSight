"""Create and read owned internal transfers; no synthetic income/expense entries."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import creation_key, financial_access, financial_mutation
from app.schemas.transfers import (
    TransferCreatedResponse,
    TransferInput,
    TransferListResponse,
    TransferResponse,
)
from app.services.sessions import SessionService
from app.services.transfers import TransferService

router = APIRouter(prefix="/api/v1/transfers", tags=["transfers"])


def transfer_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return TransferService(sessions)


@router.post("", status_code=201, response_model=TransferCreatedResponse)
def create_transfer(
    data: TransferInput,
    response: Response,
    token: Annotated[SecretStr, Depends(financial_mutation)],
    key: Annotated[UUID, Depends(creation_key)],
    service: Annotated[TransferService, Depends(transfer_service)],
):
    transfer_id = service.create(token, key, data)
    response.headers["Location"] = f"/api/v1/transfers/{transfer_id}"
    return TransferCreatedResponse(id=transfer_id)


@router.get("/{transfer_id}", response_model=TransferResponse)
def get_transfer(
    transfer_id: UUID,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[TransferService, Depends(transfer_service)],
):
    return service.get(token, transfer_id)


@router.get("", response_model=TransferListResponse)
def list_transfers(
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[TransferService, Depends(transfer_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
    account_id: UUID | None = None,
    status: Literal["planned", "posted"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    return service.list(
        token,
        limit=limit,
        offset=offset,
        account_id=account_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
