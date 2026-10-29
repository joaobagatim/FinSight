"""HTTP access to application-scoped resources."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth_cookies import AuthCookies
from app.db.session import Database
from app.services.registration import RegistrationUnavailable
from app.services.session_types import AuthContext
from app.services.sessions import AuthenticationDenied, SessionService


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_session_service(
    request: Request, database: Annotated[Database, Depends(get_database)]
) -> SessionService:
    return SessionService(database, request.app.state.settings)


def get_current_user(
    request: Request, service: Annotated[SessionService, Depends(get_session_service)]
) -> AuthContext:
    values = AuthCookies(request.app.state.settings, request).read()
    if "access" not in values:
        raise AuthenticationDenied()
    if "refresh" in values:
        service.csrf_binding(refresh=values["refresh"], access=values["access"])
    return service.authenticate(values["access"])


def get_session(database: Annotated[Database, Depends(get_database)]) -> Iterator[Session | None]:
    if database.sessions is None:
        # Let request validation finish before reporting unavailable persistence.
        yield None
        return
    try:
        with database.sessions() as session:
            yield session
    except SQLAlchemyError:
        raise RegistrationUnavailable() from None
