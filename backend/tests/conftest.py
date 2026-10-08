from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alembic import command
from app.config import Settings
from app.db import make_engine
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app(settings, engine):
    return create_app(settings, engine)


@pytest.fixture
def client(app):
    # raise_server_exceptions=False so 500s come back as real responses
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def alembic_config(url) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="session")
def migrated_engine(settings):
    """The test database, rebuilt from scratch by the real Alembic migrations."""
    cfg = alembic_config(settings.test_database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = make_engine(settings.test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine):
    """A session whose work is rolled back at the end of the test."""
    connection = migrated_engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield db
    db.close()
    transaction.rollback()
    connection.close()
