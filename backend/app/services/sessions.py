"""Own transactions for session lifecycle; HTTP transport is deliberately separate."""

import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select, union
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.refresh_tokens import (
    InvalidRefreshToken,
    generate_refresh_token,
    refresh_token_digest,
)
from app.core.security import hash_password, verify_password
from app.core.tokens import AccessTokenService, InvalidAccessToken
from app.db.session import Database
from app.models.refresh_token_history import RefreshTokenHistory
from app.models.user import User
from app.models.user_session import UserSession
from app.services.session_types import AuthContext, SessionGrant


class AuthenticationDenied(Exception):
    def __init__(self):
        super().__init__("Authentication denied")


class SessionUnavailable(Exception):
    def __init__(self):
        super().__init__("Session service unavailable")


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


class SessionService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._database = database
        self._tokens = AccessTokenService(settings)
        self._refresh_ttl = settings.auth_refresh_ttl_seconds
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise SessionUnavailable()
        return now

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        if self._database.sessions is None:
            raise SessionUnavailable()
        try:
            with self._database.sessions() as session, session.begin():
                yield session
        except SQLAlchemyError:
            raise SessionUnavailable() from None

    @staticmethod
    def _context(user: User, row: UserSession) -> AuthContext:
        return AuthContext(
            user_id=user.id,
            session_id=row.id,
            name=user.name,
            email=user.email,
            session_expires_at=row.expires_at,
        )

    def _grant(self, user: User, row: UserSession, refresh: SecretStr) -> SessionGrant:
        access = self._tokens.issue(user.id, row.id)
        claims = self._tokens.verify(access)
        return SessionGrant(
            context=self._context(user, row),
            access_token=access,
            refresh_token=refresh,
            access_expires_at=min(claims.expires_at, row.expires_at),
        )

    @staticmethod
    def _lock(session: Session, user_id: UUID, session_id: UUID) -> tuple[User, UserSession]:
        user = session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = session.scalar(
            select(UserSession)
            .where(UserSession.id == session_id, UserSession.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None or row is None:
            raise AuthenticationDenied()
        return user, row

    @staticmethod
    def _live(user: User, row: UserSession, now: datetime) -> bool:
        return user.is_active and row.revoked_at is None and row.created_at <= now < row.expires_at

    @staticmethod
    def _digest(token: str | SecretStr) -> str:
        try:
            return refresh_token_digest(token)
        except InvalidRefreshToken:
            raise AuthenticationDenied() from None

    @staticmethod
    def _resolve(session: Session, digest: str) -> tuple[UUID, UUID]:
        candidates = session.execute(
            union(
                select(UserSession.user_id, UserSession.id).where(
                    UserSession.refresh_token_hash == digest
                ),
                select(UserSession.user_id, UserSession.id)
                .join(RefreshTokenHistory, RefreshTokenHistory.session_id == UserSession.id)
                .where(RefreshTokenHistory.token_hash == digest),
            )
        ).all()
        if len(candidates) != 1:
            raise AuthenticationDenied()
        return candidates[0][0], candidates[0][1]

    @staticmethod
    def _consumed(session: Session, row: UserSession, digest: str) -> bool:
        return (
            session.scalar(
                select(RefreshTokenHistory.id).where(
                    RefreshTokenHistory.session_id == row.id,
                    RefreshTokenHistory.token_hash == digest,
                )
            )
            is not None
        )

    def login(self, email: str, password: str | SecretStr) -> SessionGrant:
        if not isinstance(email, str) or len(email) > 1024:
            raise AuthenticationDenied()
        raw = password.get_secret_value() if isinstance(password, SecretStr) else password
        if not isinstance(raw, str) or not 15 <= len(raw) <= 128:
            raise AuthenticationDenied()
        try:
            raw.encode("utf-8")
        except UnicodeEncodeError:
            raise AuthenticationDenied() from None
        normalized = email.strip().lower()
        with self._transaction() as session:
            user = session.scalar(select(User).where(User.email == normalized))
            encoded = user.password_hash if user is not None else _dummy_hash()
            valid = verify_password(raw, encoded)
            if user is None or not valid:
                raise AuthenticationDenied()
            user = session.scalar(
                select(User)
                .where(User.id == user.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                user is None
                or not user.is_active
                or user.password_hash != encoded
                or user.email != normalized
            ):
                raise AuthenticationDenied()
            now = self._now()
            refresh = generate_refresh_token()
            row = UserSession(
                id=uuid4(),
                user_id=user.id,
                refresh_token_hash=self._digest(refresh),
                created_at=now,
                expires_at=now + timedelta(seconds=self._refresh_ttl),
            )
            session.add(row)
            session.flush()
            grant = self._grant(user, row, refresh)
        return grant

    def refresh(self, token: str | SecretStr) -> SessionGrant:
        digest = self._digest(token)
        grant = None
        with self._transaction() as session:
            user, row = self._lock(session, *self._resolve(session, digest))
            now = self._now()
            if now < row.created_at:
                raise AuthenticationDenied()
            if self._consumed(session, row, digest):
                if row.revoked_at is None:
                    row.revoked_at = now
                # Do not raise inside the transaction: replay revocation must commit.
            elif row.refresh_token_hash == digest and self._live(user, row, now):
                refresh = generate_refresh_token()
                replacement = self._digest(refresh)
                if replacement == digest:
                    raise SessionUnavailable()
                session.add(RefreshTokenHistory(session_id=row.id, token_hash=digest, used_at=now))
                row.refresh_token_hash = replacement
                row.last_used_at = now
                session.flush()
                grant = self._grant(user, row, refresh)
            else:
                raise AuthenticationDenied()
        if grant is None:
            raise AuthenticationDenied()
        return grant

    def authenticate(self, token: str | SecretStr) -> AuthContext:
        claims = self._claims(token)
        with self._transaction() as session:
            pair = session.execute(
                select(User, UserSession)
                .join(UserSession, UserSession.user_id == User.id)
                .where(User.id == claims.user_id, UserSession.id == claims.session_id)
            ).one_or_none()
            now = self._now()
            if (
                pair is None
                or not self._live(*pair, now)
                or not claims.not_before <= now < claims.expires_at
            ):
                raise AuthenticationDenied()
            context = self._context(*pair)
        return context

    def _claims(self, token: str | SecretStr):
        try:
            return self._tokens.verify(token)
        except InvalidAccessToken:
            raise AuthenticationDenied() from None

    def revoke_by_refresh(self, token: str | SecretStr) -> None:
        digest = self._digest(token)
        with self._transaction() as session:
            _, row = self._lock(session, *self._resolve(session, digest))
            if row.refresh_token_hash != digest and not self._consumed(session, row, digest):
                raise AuthenticationDenied()
            self._revoke(row)

    def revoke_by_access(self, token: str | SecretStr) -> None:
        claims = self._claims(token)
        with self._transaction() as session:
            _, row = self._lock(session, claims.user_id, claims.session_id)
            self._revoke(row)

    def _revoke(self, row: UserSession) -> None:
        now = self._now()
        if now < row.created_at:
            raise AuthenticationDenied()
        if row.revoked_at is None:
            row.revoked_at = now
