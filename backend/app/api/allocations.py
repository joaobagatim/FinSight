"""Owned reservation writes and current-day funding/availability snapshots."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import creation_key, financial_access, financial_mutation
from app.schemas.allocations import (
    AllocationContextResponse,
    AllocationCreatedResponse,
    AllocationInput,
    AllocationListResponse,
    AvailabilityResponse,
    GoalFundingResponse,
    ReservationAlertsResponse,
)
from app.services.allocations import AllocationService, context_etag
from app.services.sessions import SessionService

router = APIRouter(tags=["reservations"])


def allocation_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return AllocationService(sessions)


@router.get("/api/v1/goals/{goal_id}/funding", response_model=GoalFundingResponse)
def goal_funding(
    goal_id: UUID,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[AllocationService, Depends(allocation_service)],
):
    return service.funding(token, goal_id)


@router.get("/api/v1/goals/{goal_id}/allocation-context", response_model=AllocationContextResponse)
def allocation_context(
    goal_id: UUID,
    account_id: UUID,
    response: Response,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[AllocationService, Depends(allocation_service)],
):
    result = service.context(token, goal_id, account_id)
    response.headers["ETag"] = context_etag(result)
    return result


@router.get("/api/v1/accounts/{account_id}/availability", response_model=AvailabilityResponse)
def account_availability(
    account_id: UUID,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[AllocationService, Depends(allocation_service)],
):
    return service.availability(token, account_id)


@router.get("/api/v1/reservations/alerts", response_model=ReservationAlertsResponse)
def reservation_alerts(
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[AllocationService, Depends(allocation_service)],
):
    return service.alerts(token)


@router.get("/api/v1/goals/{goal_id}/allocations", response_model=AllocationListResponse)
def list_allocations(
    goal_id: UUID,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[AllocationService, Depends(allocation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    return service.list(token, goal_id, limit=limit, offset=offset)


@router.post(
    "/api/v1/goals/{goal_id}/allocations", status_code=201, response_model=AllocationCreatedResponse
)
def create_allocation(
    goal_id: UUID,
    data: AllocationInput,
    token: Annotated[SecretStr, Depends(financial_mutation)],
    key: Annotated[UUID, Depends(creation_key)],
    service: Annotated[AllocationService, Depends(allocation_service)],
    etag: Annotated[
        str, Header(alias="If-Match", min_length=66, max_length=66, pattern=r'^"[0-9a-f]{64}"$')
    ],
):
    return AllocationCreatedResponse(id=service.create(token, goal_id, key, data, etag))
