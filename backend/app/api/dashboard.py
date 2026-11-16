"""Authenticated, read-only dashboard activity summary."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import UUID4, SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import financial_access
from app.schemas.dashboard import DashboardBreakdownResponse, DashboardSummaryResponse
from app.services.dashboard import DashboardService
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def dashboard_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return DashboardService(sessions)


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_summary(
    date_from: date,
    date_to: date,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[DashboardService, Depends(dashboard_service)],
    scope: Literal["active", "all", "selected"] = "active",
    account_id: Annotated[list[UUID4] | None, Query(max_length=100)] = None,
):
    return service.summary(
        token, date_from=date_from, date_to=date_to, scope=scope, account_ids=account_id
    )


@router.get("/breakdown", response_model=DashboardBreakdownResponse)
def get_breakdown(
    date_from: date,
    date_to: date,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[DashboardService, Depends(dashboard_service)],
    scope: Literal["active", "all", "selected"] = "active",
    account_id: Annotated[list[UUID4] | None, Query(max_length=100)] = None,
):
    return service.summary(
        token,
        date_from=date_from,
        date_to=date_to,
        scope=scope,
        account_ids=account_id,
        include_breakdown=True,
    )
