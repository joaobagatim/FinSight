"""Cookie-authenticated categories; ownership is always resolved server-side."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import SecretStr

from app.api.dependencies import get_session_service
from app.api.financial_auth import financial_access as category_access
from app.api.financial_auth import financial_mutation as category_mutation
from app.schemas.categories import (
    CategoryInput,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdateInput,
)
from app.services.categories import CategoryService, category_etag
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


def category_service(sessions: Annotated[SessionService, Depends(get_session_service)]):
    return CategoryService(sessions)


@router.post("", status_code=201, response_model=CategoryResponse)
def create_category(
    data: CategoryInput,
    response: Response,
    token: Annotated[SecretStr, Depends(category_mutation)],
    service: Annotated[CategoryService, Depends(category_service)],
):
    result = service.create(token, data)
    response.headers["Location"] = f"/api/v1/categories/{result.id}"
    response.headers["ETag"] = category_etag(result)
    return result


@router.get("", response_model=CategoryListResponse)
def list_categories(
    token: Annotated[SecretStr, Depends(category_access)],
    service: Annotated[CategoryService, Depends(category_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
    type: Literal["income", "expense"] | None = None,
):
    return service.list(token, limit=limit, offset=offset, kind=type)


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    category_id: UUID,
    response: Response,
    token: Annotated[SecretStr, Depends(category_access)],
    service: Annotated[CategoryService, Depends(category_service)],
):
    result = service.get(token, category_id)
    response.headers["ETag"] = category_etag(result)
    return result


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: UUID,
    data: CategoryUpdateInput,
    response: Response,
    token: Annotated[SecretStr, Depends(category_mutation)],
    service: Annotated[CategoryService, Depends(category_service)],
    etag: Annotated[
        str, Header(alias="If-Match", min_length=66, max_length=66, pattern=r'^"[0-9a-f]{64}"$')
    ],
):
    result = service.update(token, category_id, data, etag)
    response.headers["ETag"] = category_etag(result)
    return result
