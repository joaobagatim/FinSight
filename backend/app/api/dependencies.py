"""HTTP access to application-scoped resources."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.services.registration import RegistrationUnavailable


def get_database(request: Request) -> Database:
    return request.app.state.database


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
