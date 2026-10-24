"""Lazy PostgreSQL connections and explicit session lifecycle."""

from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def build_database_url(settings: Settings) -> URL:
    if settings.db_password is None:
        raise ValueError("Database password is not configured")
    return URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


class Database:
    def __init__(self, settings: Settings):
        self.engine: Engine | None = None
        self.sessions: sessionmaker[Session] | None = None
        if settings.db_password is None:
            return
        options = f"-c timezone=UTC -c statement_timeout={settings.db_statement_timeout_ms}"
        self.engine = create_engine(
            build_database_url(settings),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=settings.db_pool_timeout,
            hide_parameters=True,
            connect_args={
                "connect_timeout": settings.db_connect_timeout,
                "application_name": "finsight-api",
                "options": options,
            },
        )
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def check_connection(self) -> bool:
        if self.engine is None:
            return False
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
