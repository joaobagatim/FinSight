"""Process health, independent of external services."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_database
from app.db.session import Database

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Confirm the API can respond; database readiness is a separate concern."""
    return HealthResponse()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Database unavailable"}},
)
def readiness(
    response: Response, database: Annotated[Database, Depends(get_database)]
) -> ReadinessResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        available = database.check_connection()
    except SQLAlchemyError:
        logger.warning("Database readiness check failed")
        available = False
    if not available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
