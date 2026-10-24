"""Safe URL construction and disconnected startup."""

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.db.session import Database, build_database_url


def test_url_preserves_special_characters_without_string_interpolation():
    marker = "synthetic@:/%?# password"
    settings = Settings(_env_file=None, db_password=SecretStr(marker))

    url = build_database_url(settings)

    assert url.drivername == "postgresql+psycopg"
    assert url.password == marker
    assert marker not in str(url)
    assert marker not in repr(settings)
    assert marker not in settings.model_dump_json()


def test_missing_password_cannot_build_connection_url():
    with pytest.raises(ValueError, match="not configured"):
        build_database_url(Settings(_env_file=None))


def test_database_without_credentials_starts_disconnected():
    database = Database(Settings(_env_file=None))

    assert database.check_connection() is False
    assert database.sessions is None
    database.dispose()
