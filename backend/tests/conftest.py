from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from app.ai import llm_provider
from app.auth.passwords import hash_password
from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import Pantry, User
from app.storage import LocalStorage
from tests.fakes import FakeLLM

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture
def engine(settings, migrated_engine):
    engine = make_engine(settings.test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True, scope="session")
def no_aws_calls():
    """Tests never talk to AWS. Any attempt to build a boto3 session or client fails loudly."""
    import boto3

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to create a boto3 session or client")

    original = (boto3.Session, boto3.client, boto3.setup_default_session)
    boto3.Session = boto3.client = boto3.setup_default_session = refuse
    yield
    boto3.Session, boto3.client, boto3.setup_default_session = original


@pytest.fixture
def sleeps(monkeypatch):
    """Retry backoff sleeps are recorded, not waited for."""
    recorded: list[float] = []
    monkeypatch.setattr(llm_provider, "_sleep", recorded.append)
    return recorded


@pytest.fixture(autouse=True)
def _no_real_sleep(sleeps):
    return sleeps


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "uploads")


@pytest.fixture
def app(settings, engine, llm, storage):
    from app.services.forecasting import ForecastConfig

    # small, quick trees: the API tests check plumbing, not accuracy
    fast = ForecastConfig(
        n_estimators=15, num_leaves=7, min_data_in_leaf=5, num_threads=2, min_history_weeks=30
    )
    return create_app(settings, engine, llm=llm, storage=storage, forecast_config=fast)


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
    # Donations point at users (created_by, reviewed_by), so they have to go first.
    with migrated_engine.begin() as conn:
        conn.execute(text(WIPE_DONATIONS))
    with Session(migrated_engine) as db:
        db.query(User).filter(User.email.in_(vars(emails).values())).delete()
        db.query(Pantry).filter(Pantry.id.in_([PANTRY_A, PANTRY_B])).delete()
        db.commit()


def login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


WIPE_DONATIONS = (
    "TRUNCATE inventory_lots, donation_items, donations, donors RESTART IDENTITY CASCADE"
)


@pytest.fixture
def clean_donations(migrated_engine):
    """Empty the donation-related tables before and after a test (they are committed by the API)."""

    def wipe():
        with migrated_engine.begin() as conn:
            conn.execute(text(WIPE_DONATIONS))

    wipe()
    yield
    wipe()


def row_count(engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


FORECAST_PANTRIES = (911, 912, 913)
FORECAST_CATEGORIES = (1, 2)  # produce, dairy
FORECAST_WEEKS = 70


@pytest.fixture
def forecast_data(migrated_engine):
    """A small committed dataset the forecast endpoints can read: 3 pantries x 2 categories x 70
    weeks of distributions, weather and calendar rows, and two shortage reports."""
    from datetime import date, timedelta

    import numpy as np

    from app.constants import COUNTIES
    from app.models import Distribution, ShortageReport, WeeklyContext
    from app.services.calendar_rules import benefit_week, school_holiday

    last = date(2026, 9, 28)
    weeks = [last - timedelta(weeks=FORECAST_WEEKS - 1 - k) for k in range(FORECAST_WEEKS)]
    counties = list(COUNTIES)[:3]
    with Session(migrated_engine) as db:
        for i, pantry_id in enumerate(FORECAST_PANTRIES):
            db.add(
                Pantry(
                    id=pantry_id,
                    name=f"Forecast Pantry {i + 1}",
                    county=counties[i],
                    latitude=40.1,
                    longitude=-83.2,
                    cold_capacity_lbs=1000,
                    dry_capacity_lbs=2000,
                    baseline_households=300 + 100 * i,
                )  # fmt: skip
            )
        db.flush()
        for county in counties:
            for k, week in enumerate(weeks):
                db.add(
                    WeeklyContext(
                        county=county,
                        week_start=week,
                        avg_temp_f=50 + 20 * np.sin(2 * np.pi * (k - 13) / 52),
                        precip_in=0.4,
                        school_holiday=school_holiday(county, week),
                        benefit_week=benefit_week(county, week),
                    )  # fmt: skip
                )
        for i, pantry_id in enumerate(FORECAST_PANTRIES):
            for category_id in FORECAST_CATEGORIES:
                for k, week in enumerate(weeks):
                    season = 1 + 0.3 * np.sin(2 * np.pi * k / 52)
                    db.add(
                        Distribution(
                            pantry_id=pantry_id,
                            category_id=category_id,
                            week_start=week,
                            lbs=round(300 * (i + 1) * (1 + 0.2 * category_id) * season, 2),
                            households=100 * (i + 1) + k % 5,
                        )  # fmt: skip
                    )
        db.add(
            ShortageReport(
                pantry_id=911,
                category_id=1,
                week_start=weeks[40],
                severity=2,
                households_turned_away=10,
            )  # fmt: skip
        )
        db.add(
            ShortageReport(
                pantry_id=912,
                category_id=2,
                week_start=weeks[55],
                severity=3,
                households_turned_away=20,
            )  # fmt: skip
        )
        db.commit()
    yield SimpleNamespace(weeks=weeks, last=weeks[-1], next=weeks[-1] + timedelta(weeks=1))
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE forecasts, forecast_runs, distributions, shortage_reports, "
                "weekly_context RESTART IDENTITY CASCADE"
            )
        )
        conn.execute(text("DELETE FROM pantries WHERE id IN (911, 912, 913)"))
