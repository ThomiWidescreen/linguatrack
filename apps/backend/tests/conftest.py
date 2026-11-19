import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from linguatrack.config import get_settings
from linguatrack.db import engine
from linguatrack.main import app


@pytest.fixture(scope="session", autouse=True)
def isolated_database():
    """Only the freshly created random database is dropped; never the user's database."""
    original = get_settings()
    admin_url = make_url(os.environ.get("TEST_ADMIN_DATABASE_URL", original.migration_database_url))
    test_name = "linguatrack_test_" + uuid4().hex
    admin = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        if not connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname='linguatrack_app'")):
            connection.execute(
                text(
                    "CREATE ROLE linguatrack_app LOGIN PASSWORD 'local_app' NOSUPERUSER NOBYPASSRLS"
                )
            )
        connection.execute(text(f'CREATE DATABASE "{test_name}"'))
    overrides = {
        "DATABASE_URL": admin_url.set(
            database=test_name,
            username="linguatrack_app",
            password="local_app",
        ).render_as_string(hide_password=False),
        "MIGRATION_DATABASE_URL": admin_url.set(database=test_name).render_as_string(
            hide_password=False
        ),
        "ENVIRONMENT": "test",
    }
    saved = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    get_settings.cache_clear()
    engine.cache_clear()
    migration_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(migration_config, "head")
    try:
        yield
    finally:
        engine().dispose()
        engine.cache_clear()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{test_name}" WITH (FORCE)'))
        admin.dispose()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.headers["X-Dev-User"] = str(uuid4())
        yield client
