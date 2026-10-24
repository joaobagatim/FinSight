"""Keep tests independent of machine configuration and local .env files."""

import os

import pytest


@pytest.fixture(autouse=True)
def clear_application_environment(monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith("FINSIGHT_"):
            monkeypatch.delenv(name)
