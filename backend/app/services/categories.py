"""Per-user categories, conditional metadata updates and preserved history."""

import hashlib
import hmac
import json
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Category
from app.schemas.categories import (
    CategoryInput,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdateInput,
)
from app.services.sessions import SessionService


class CategoryNotFound(Exception):
    pass


class CategoryConflict(Exception):
    pass


class CategoryStale(Exception):
    pass


def category_etag(category: CategoryResponse) -> str:
    canonical = json.dumps(category.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(canonical.encode()).hexdigest() + '"'


def flush_category(session):
    try:
        session.flush()
    except IntegrityError as error:
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == (
            "uq_categories_user_type_normalized_name"
        ):
            raise CategoryConflict() from None
        raise


class CategoryService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    def create(self, token: SecretStr, data: CategoryInput) -> CategoryResponse:
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = Category(user_id=owner.user_id, **data.model_dump())
            session.add(row)
            flush_category(session)
            result = CategoryResponse.model_validate(row)
        return result

    def list(self, token: SecretStr, *, limit: int, offset: int, kind: str | None):
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = select(Category).where(Category.user_id == owner.user_id)
            if kind is not None:
                query = query.where(Category.type == kind)
            rows = session.scalars(
                query.order_by(Category.created_at, Category.id).limit(limit + 1).offset(offset)
            ).all()
            result = CategoryListResponse(
                items=[CategoryResponse.model_validate(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result

    def get(self, token: SecretStr, category_id: UUID) -> CategoryResponse:
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.scalar(
                select(Category).where(
                    Category.id == category_id, Category.user_id == owner.user_id
                )
            )
            if row is None:
                raise CategoryNotFound()
            result = CategoryResponse.model_validate(row)
        return result

    def update(self, token: SecretStr, category_id: UUID, data: CategoryUpdateInput, etag: str):
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(Category)
                .where(Category.id == category_id, Category.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise CategoryNotFound()
            if not hmac.compare_digest(category_etag(CategoryResponse.model_validate(row)), etag):
                raise CategoryStale()
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(row, key, value)
            flush_category(session)
            result = CategoryResponse.model_validate(row)
        return result
