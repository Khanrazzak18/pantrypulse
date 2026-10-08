from datetime import UTC, date, datetime
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
    created = create_app(settings, engine, llm=llm, storage=storage, forecast_config=fast)
    created.state.today = lambda: date(2026, 10, 6)  # a Tuesday inside the forecast week
    return created


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
        conn.execute(
            text(
                "DELETE FROM shortage_reports WHERE reported_by IS NOT NULL OR pantry_id IN (901, 902)"
            )
        )
        conn.execute(text("DELETE FROM monthly_summaries WHERE approved_by IS NOT NULL"))
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


ALLOC_PANTRIES = (921, 922, 923)
ALLOC_WEEK = date(2026, 10, 5)  # the forecast week (a Monday)


@pytest.fixture
def allocation_world(migrated_engine, people):
    """A tiny world to allocate in: three pantries, a completed forward forecast for the week of
    2026-10-05, and five lots. `today` is fixed at 2026-10-06 by the app fixture."""
    from datetime import date as d

    from app.models import (
        Donation,
        DonationItem,
        Donor,
        Forecast,
        ForecastRun,
        InventoryLot,
    )

    wants = {  # (pantry, category): (p50, p90); categories 1 produce, 2 dairy, 6 canned
        (921, 1): (600, 700), (921, 2): (300, 350), (921, 6): (400, 450),
        (922, 1): (300, 350), (922, 2): (150, 180), (922, 6): (200, 230),
        (923, 1): (100, 120), (923, 2): (80, 100), (923, 6): (100, 120),
    }  # fmt: skip
    coords = {921: (40.1, -83.1), 922: (40.3, -82.8), 923: (39.8, -83.2)}
    lot_specs = [  # key, category, storage, lbs, expiry
        ("A", 1, "refrigerated", 500, d(2026, 10, 9)),
        ("B", 1, "refrigerated", 800, d(2026, 10, 20)),
        ("C", 2, "refrigerated", 400, d(2026, 10, 12)),
        ("D", 6, "ambient", 2000, d(2027, 6, 1)),
        ("E", 1, "refrigerated", 300, d(2026, 10, 3)),  # already expired on the delivery date
    ]
    lots = {}
    with Session(migrated_engine) as db:
        for pid in ALLOC_PANTRIES:
            lat, lon = coords[pid]
            db.add(
                Pantry(
                    id=pid,
                    name=f"Alloc Pantry {pid - 920}",
                    county="Ashford",
                    latitude=lat,
                    longitude=lon,
                    cold_capacity_lbs=150 if pid == 923 else 5000,
                    dry_capacity_lbs=8000,
                    baseline_households=300,
                )  # fmt: skip
            )
        donor = Donor(name="Alloc Donor", donor_type="grocery")
        db.add(donor)
        db.flush()
        donation = Donation(
            donor_id=donor.id, source_type="historical", status="confirmed",
            received_at=datetime(2026, 10, 3, 10, 0, tzinfo=UTC),
        )  # fmt: skip
        db.add(donation)
        db.flush()
        for key, category_id, storage, lbs, expiry in lot_specs:
            item = DonationItem(
                donation_id=donation.id, name=f"Lot {key} food", category_id=category_id,
                quantity=1, unit="case", estimated_weight_lbs=lbs, expiry_date=expiry,
                storage_type=storage,
            )  # fmt: skip
            db.add(item)
            db.flush()
            lot = InventoryLot(
                donation_item_id=item.id, category_id=category_id, storage_type=storage,
                received_lbs=lbs, remaining_lbs=lbs, expired_lbs=0, received_date=d(2026, 10, 3),
                expiry_date=expiry, status="available",
            )  # fmt: skip
            db.add(lot)
            db.flush()
            lots[key] = lot.id
        run = ForecastRun(
            model_name="lightgbm", kind="forward", status="completed", train_start=d(2023, 10, 2),
            train_end=d(2026, 9, 28), horizon_week_start=ALLOC_WEEK, model_key="forecasts/run-x",
        )  # fmt: skip
        db.add(run)
        db.flush()
        for (pid, cid), (p50, p90) in wants.items():
            db.add(
                Forecast(
                    forecast_run_id=run.id,
                    pantry_id=pid,
                    category_id=cid,
                    week_start=ALLOC_WEEK,
                    p10_lbs=p50 * 0.8,
                    p50_lbs=p50,
                    p90_lbs=p90,
                    baseline_lbs=p50,
                )  # fmt: skip
            )
        db.commit()
        forecast_run_id = run.id
    yield SimpleNamespace(lots=lots, wants=wants, forecast_run_id=forecast_run_id, week=ALLOC_WEEK)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE allocation_edits, allocations, allocation_runs, forecasts, forecast_runs, "
                "inventory_lots, donation_items, donations, donors RESTART IDENTITY CASCADE"
            )
        )
        conn.execute(text("DELETE FROM pantries WHERE id IN (921, 922, 923)"))


IMPACT_PANTRIES = (931, 932)
IMPACT_W1, IMPACT_W2 = date(2026, 9, 7), date(2026, 9, 14)  # both Mondays, both in September


@pytest.fixture
def impact_world(migrated_engine):
    """Two pantries, two weeks of distributions, three shortage reports and three lots, small
    enough to work every dashboard number out by hand (see test_dashboard_metrics.py).
    Categories: 1 produce (perishable), 6 canned (not)."""
    from app.models import (
        Distribution,
        Donation,
        DonationItem,
        Donor,
        InventoryLot,
        ShortageReport,
    )

    with Session(migrated_engine) as db:
        for pid in IMPACT_PANTRIES:
            db.add(
                Pantry(
                    id=pid,
                    name=f"Impact Pantry {pid - 930}",
                    county="Ashford",
                    latitude=40.1,
                    longitude=-83.1,
                    cold_capacity_lbs=1000,
                    dry_capacity_lbs=2000,
                    baseline_households=100,
                )  # fmt: skip
            )
        db.flush()
        rows = [  # pantry, category, week, lbs, households
            (931, 1, IMPACT_W1, 100, 50), (931, 6, IMPACT_W1, 200, 50),
            (931, 1, IMPACT_W2, 120, 60), (931, 6, IMPACT_W2, 180, 60),
            (932, 1, IMPACT_W1, 40, 20), (932, 6, IMPACT_W1, 60, 20),
            (932, 1, IMPACT_W2, 10, 5),
        ]  # fmt: skip
        for p, c, w, lbs, hh in rows:
            db.add(Distribution(pantry_id=p, category_id=c, week_start=w, lbs=lbs, households=hh))
        for p, c, w, sev in [
            (931, 1, IMPACT_W1, 2),
            (932, 1, IMPACT_W1, 3),
            (931, 6, IMPACT_W2, 1),
        ]:
            db.add(
                ShortageReport(
                    pantry_id=p, category_id=c, week_start=w, severity=sev, households_turned_away=0
                )  # fmt: skip
            )
        donor = Donor(name="Impact Donor", donor_type="grocery")
        db.add(donor)
        db.flush()
        donation = Donation(
            donor_id=donor.id, source_type="historical", status="confirmed",
            received_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        )  # fmt: skip
        db.add(donation)
        db.flush()
        for category_id, storage, received, expired, day in [
            (1, "refrigerated", 1000, 120, date(2026, 9, 8)),
            (1, "refrigerated", 500, 30, date(2026, 9, 16)),
            (6, "ambient", 2000, 500, date(2026, 9, 8)),
        ]:
            item = DonationItem(
                donation_id=donation.id, name="Impact food", category_id=category_id, quantity=1,
                unit="case", estimated_weight_lbs=received, storage_type=storage,
            )  # fmt: skip
            db.add(item)
            db.flush()
            db.add(
                InventoryLot(
                    donation_item_id=item.id,
                    category_id=category_id,
                    storage_type=storage,
                    received_lbs=received,
                    remaining_lbs=0,
                    expired_lbs=expired,
                    received_date=day,
                    expiry_date=day,
                    status="depleted",
                )  # fmt: skip
            )
        db.commit()
    yield SimpleNamespace(w1=IMPACT_W1, w2=IMPACT_W2)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE distributions, shortage_reports, monthly_summaries, inventory_lots, "
                "donation_items, donations, donors RESTART IDENTITY CASCADE"
            )
        )
        conn.execute(text("DELETE FROM pantries WHERE id IN (931, 932)"))
