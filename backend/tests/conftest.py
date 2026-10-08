from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alembic import command
from app.auth.passwords import hash_password
from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import Pantry, User

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture
def engine(settings, migrated_engine):
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


PASSWORD = "correct-horse-battery"
PANTRY_A, PANTRY_B = 901, 902  # ids that cannot clash with rolled-back fixtures elsewhere


@pytest.fixture(scope="session")
def password_hash() -> str:
    return hash_password(PASSWORD)  # hashing is slow on purpose; do it once


@pytest.fixture
def people(migrated_engine, password_hash):
    """Committed users the API can see: one of each role plus an inactive coordinator.
    The pantry manager belongs to pantry A. Removed again after the test."""
    emails = SimpleNamespace(
        coordinator="coord@example.org",
        admin="admin@example.org",
        manager="manager@example.org",
        inactive="inactive@example.org",
    )

    def user(email, role, pantry_id=None, active=True):
        return User(
            email=email, password_hash=password_hash, full_name=email.split("@")[0].title(),
            role=role, pantry_id=pantry_id, is_active=active,
        )  # fmt: skip

    def pantry(pid, name):
        return Pantry(
            id=pid, name=name, county="Ashford", latitude=40.1, longitude=-83.2,
            cold_capacity_lbs=1000, dry_capacity_lbs=2000, baseline_households=300,
        )  # fmt: skip

    with Session(migrated_engine) as db:
        db.add_all([pantry(PANTRY_A, "Auth Pantry A"), pantry(PANTRY_B, "Auth Pantry B")])
        db.flush()
        db.add_all(
            [
                user(emails.coordinator, "coordinator"),
                user(emails.admin, "admin"),
                user(emails.manager, "pantry_manager", PANTRY_A),
                user(emails.inactive, "coordinator", active=False),
            ]
        )
        db.commit()
    yield emails
    with Session(migrated_engine) as db:
        db.query(User).filter(User.email.in_(vars(emails).values())).delete()
        db.query(Pantry).filter(Pantry.id.in_([PANTRY_A, PANTRY_B])).delete()
        db.commit()


def login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})
