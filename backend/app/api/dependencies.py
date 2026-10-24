"""HTTP access to application-scoped resources."""

from fastapi import Request

from app.db.session import Database


def get_database(request: Request) -> Database:
    return request.app.state.database
