"""Persistent creation retries and conditional goal metadata updates per owner."""

import hashlib
import hmac
import json
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select

from app.models import FinancialGoal, GoalCreationRequest
from app.schemas.goals import GoalInput, GoalListResponse, GoalResponse, GoalUpdateInput
from app.services.sessions import SessionService


class GoalNotFound(Exception):
    pass


class GoalConflict(Exception):
    pass


class GoalStale(Exception):
    pass


def goal_etag(data: GoalResponse) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(canonical.encode()).hexdigest() + '"'


class GoalService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    def create(self, token: SecretStr, key: UUID, data: GoalInput) -> UUID:
        canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            previous = session.get(GoalCreationRequest, (owner.user_id, key))
            if previous is not None:
                if not hmac.compare_digest(previous.request_hash, digest):
                    raise GoalConflict()
                identity = previous.goal_id
            else:
                row = FinancialGoal(user_id=owner.user_id, status="active", **data.model_dump())
                session.add(row)
                session.flush()
                identity = row.id
                session.add(
                    GoalCreationRequest(
                        user_id=owner.user_id,
                        idempotency_key=key,
                        request_hash=digest,
                        goal_id=identity,
                    )
                )
                session.flush()
        return identity

    def get(self, token: SecretStr, goal_id: UUID) -> GoalResponse:
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.scalar(
                select(FinancialGoal).where(
                    FinancialGoal.id == goal_id, FinancialGoal.user_id == owner.user_id
                )
            )
            if row is None:
                raise GoalNotFound()
            result = GoalResponse.model_validate(row)
        return result

    def list(self, token: SecretStr, *, limit: int, offset: int, status: str | None):
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = select(FinancialGoal).where(FinancialGoal.user_id == owner.user_id)
            if status is not None:
                query = query.where(FinancialGoal.status == status)
            rows = session.scalars(
                query.order_by(FinancialGoal.created_at, FinancialGoal.id)
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = GoalListResponse(
                items=[GoalResponse.model_validate(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result

    def update(self, token: SecretStr, goal_id: UUID, data: GoalUpdateInput, etag: str):
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(FinancialGoal)
                .where(FinancialGoal.id == goal_id, FinancialGoal.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise GoalNotFound()
            if not hmac.compare_digest(goal_etag(GoalResponse.model_validate(row)), etag):
                raise GoalStale()
            for field, value in data.model_dump(exclude_unset=True).items():
                setattr(row, field, value)
            session.flush()
            # Status is an explicit decision about the objective, never a money movement.
            result = GoalResponse.model_validate(row)
        return result
