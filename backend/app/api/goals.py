"""Goal metadata routes; session authorization is required for every resource."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import creation_key, financial_access, financial_mutation
from app.schemas.goals import (
    GoalCreatedResponse,
    GoalInput,
    GoalListResponse,
    GoalResponse,
    GoalUpdateInput,
)
from app.services.goals import GoalService, goal_etag
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/goals", tags=["goals"])


def goal_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return GoalService(sessions)


@router.post("", status_code=201, response_model=GoalCreatedResponse)
def create_goal(
    data: GoalInput,
    response: Response,
    token: Annotated[SecretStr, Depends(financial_mutation)],
    key: Annotated[UUID, Depends(creation_key)],
    service: Annotated[GoalService, Depends(goal_service)],
):
    identity = service.create(token, key, data)
    response.headers["Location"] = f"/api/v1/goals/{identity}"
    return GoalCreatedResponse(id=identity)


@router.get("", response_model=GoalListResponse)
def list_goals(
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[GoalService, Depends(goal_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
    status: Literal["active", "completed", "cancelled"] | None = None,
):
    return service.list(token, limit=limit, offset=offset, status=status)


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal(
    goal_id: UUID,
    response: Response,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[GoalService, Depends(goal_service)],
):
    result = service.get(token, goal_id)
    response.headers["ETag"] = goal_etag(result)
    return result


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: UUID,
    data: GoalUpdateInput,
    response: Response,
    token: Annotated[SecretStr, Depends(financial_mutation)],
    service: Annotated[GoalService, Depends(goal_service)],
    etag: Annotated[
        str, Header(alias="If-Match", min_length=66, max_length=66, pattern=r'^"[0-9a-f]{64}"$')
    ],
):
    result = service.update(token, goal_id, data, etag)
    response.headers["ETag"] = goal_etag(result)
    return result
