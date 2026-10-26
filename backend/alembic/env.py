"""Use application settings online and a credential-free PostgreSQL dialect offline."""

from alembic import context
from alembic.util import CommandError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from app.models import User, UserSession  # noqa: F401 -- register model metadata

config = context.config
target_metadata = Base.metadata


def run_with_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # Callers may supply a connection to keep tests on their isolated database.
    connection = config.attributes.get("connection")
    if connection is not None:
        run_with_connection(connection)
        return

    database = Database(Settings())
    try:
        if database.engine is None:
            raise CommandError("Configure a database password before running migrations")
        with database.engine.connect() as connection:
            run_with_connection(connection)
    finally:
        database.dispose()


try:
    if context.is_offline_mode():
        context.configure(
            dialect_name="postgresql",
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        run_migrations_online()
except (ValidationError, SQLAlchemyError):
    # Do not expose driver errors, SQL parameters or settings through the CLI.
    raise CommandError("Migration failed; check database configuration and availability") from None
