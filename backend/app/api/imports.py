"""Sensitive owned CSV preview operations, intentionally without confirmation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import creation_key, financial_access, financial_mutation
from app.schemas.imports import (
    ImportCreatedResponse,
    ImportInput,
    ImportInspectionResponse,
    ImportJobResponse,
    ImportListResponse,
    ImportRowsResponse,
    ImportSourceInput,
)
from app.services.imports import ImportService
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


def import_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return ImportService(sessions)


@router.post("/inspect", response_model=ImportInspectionResponse)
def inspect_source(
    data: ImportSourceInput,
    token: Annotated[SecretStr, Depends(financial_mutation)],
    service: Annotated[ImportService, Depends(import_service)],
):
    return service.inspect(token, data)


@router.post("", status_code=201, response_model=ImportCreatedResponse)
def create_preview(
    data: ImportInput,
    response: Response,
    token: Annotated[SecretStr, Depends(financial_mutation)],
    key: Annotated[UUID, Depends(creation_key)],
    service: Annotated[ImportService, Depends(import_service)],
):
    identity = service.create(token, key, data)
    response.headers["Location"] = f"/api/v1/imports/{identity}"
    return ImportCreatedResponse(id=identity)


@router.get("", response_model=ImportListResponse)
def list_previews(
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[ImportService, Depends(import_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    return service.list(token, limit=limit, offset=offset)


@router.get("/{identity}", response_model=ImportJobResponse)
def get_preview(
    identity: UUID,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[ImportService, Depends(import_service)],
):
    return service.get(token, identity)


@router.get("/{identity}/rows", response_model=ImportRowsResponse)
def get_preview_rows(
    identity: UUID,
    token: Annotated[SecretStr, Depends(financial_access)],
    service: Annotated[ImportService, Depends(import_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    return service.rows(token, identity, limit=limit, offset=offset)
