import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import make_engine
from app.main import create_app


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
