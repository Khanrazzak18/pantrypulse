"""Every table rejects bad data at the database level, not just in Python."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Allocation,
    AllocationEdit,
    AllocationRun,
    Category,
    Distribution,
    Donation,
    DonationItem,
    Donor,
    Forecast,
    ForecastRun,
    InventoryLot,
    MonthlySummary,
    Pantry,
    ShortageReport,
    User,
    WeeklyContext,
)

MONDAY = date(2026, 9, 28)
TUESDAY = date(2026, 9, 29)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def b(session):
    """One valid row in every table, so tests can break one thing at a time."""
    protein = session.scalar(select(Category).where(Category.name == "protein"))
    pantry = Pantry(
        id=1, name="Pantry 01", county="Ashford", latitude=40.1, longitude=-83.2,
        cold_capacity_lbs=5000, dry_capacity_lbs=8000, baseline_households=450,
    )  # fmt: skip
    donor = Donor(name="Test Mart", donor_type="grocery")
    coordinator = User(
        email="c@example.org", password_hash="x", full_name="Coord", role="coordinator"
    )
    session.add_all([pantry, donor, coordinator])
    session.flush()
    manager = User(
        email="m@example.org", password_hash="x", full_name="Mgr",
        role="pantry_manager", pantry_id=pantry.id,
    )  # fmt: skip
    donation = Donation(
        donor_id=donor.id, source_type="email", status="pending_review", received_at=NOW
    )
    session.add_all([manager, donation])
    session.flush()
    item = DonationItem(
        donation_id=donation.id, name="Chicken thighs", category_id=protein.id, quantity=10,
        unit="case", estimated_weight_lbs=400, expiry_date=date(2026, 10, 5),
        storage_type="refrigerated",
    )  # fmt: skip
    session.add(item)
    session.flush()
    lot = InventoryLot(
        donation_item_id=item.id, category_id=protein.id, storage_type="refrigerated",
        received_lbs=400, remaining_lbs=400, expired_lbs=0, received_date=date(2026, 10, 1),
        expiry_date=date(2026, 10, 5), status="available",
    )  # fmt: skip
    session.add(lot)
    session.add(Distribution(
        pantry_id=pantry.id, category_id=protein.id, week_start=MONDAY, lbs=900, households=120
    ))  # fmt: skip
    session.add(ShortageReport(
        pantry_id=pantry.id, category_id=protein.id, week_start=MONDAY, severity=2,
        households_turned_away=10,
    ))  # fmt: skip
    session.add(WeeklyContext(
        county="Ashford", week_start=MONDAY, avg_temp_f=60.5, precip_in=0.4,
        school_holiday=False, benefit_week=True,
    ))  # fmt: skip
    run = ForecastRun(
        model_name="lightgbm", wape_lightgbm=0.18, wape_baseline=0.27,
        train_start=date(2023, 10, 2), train_end=date(2026, 9, 21),
        horizon_week_start=MONDAY, status="completed",
    )  # fmt: skip
    session.add(run)
    session.flush()
    session.add(Forecast(
        forecast_run_id=run.id, pantry_id=pantry.id, category_id=protein.id,
        week_start=MONDAY, p10_lbs=700, p50_lbs=900, p90_lbs=1200,
    ))  # fmt: skip
    alloc_run = AllocationRun(forecast_run_id=run.id, created_by=coordinator.id, status="draft")
    session.add(alloc_run)
    session.flush()
    allocation = Allocation(
        allocation_run_id=alloc_run.id, lot_id=lot.id, pantry_id=pantry.id,
        recommended_lbs=300, reason="Pantry 01: forecast short 300 lb protein", status="proposed",
    )  # fmt: skip
    session.add(allocation)
    session.add(MonthlySummary(
        month=date(2026, 9, 1), aggregates={"spoilage_pct": 11.8}, ai_draft="Draft text",
        status="draft",
    ))  # fmt: skip
    session.flush()
    return SimpleNamespace(
        protein=protein, pantry=pantry, donor=donor, coordinator=coordinator, manager=manager,
        donation=donation, item=item, lot=lot, run=run, alloc_run=alloc_run,
        allocation=allocation,
    )  # fmt: skip


def test_valid_rows_in_every_table_are_accepted(session, b):
    """Positive control: if this fails, the rejection tests below prove nothing."""
    assert b.allocation.id is not None
    assert session.get(Pantry, 1).name == "Pantry 01"


def test_the_eight_fixed_categories_exist_with_perishable_flags(session):
    rows = {c.name: c.perishable for c in session.scalars(select(Category))}
    assert rows == {
        "produce": True, "dairy": True, "protein": True, "bakery": True,
        "frozen": False, "canned": False, "dry_goods": False, "beverages": False,
    }  # fmt: skip


def item(b, **kw):
    base = dict(
        donation_id=b.donation.id, name="Beans", category_id=b.protein.id, quantity=1,
        unit="case", estimated_weight_lbs=10, storage_type="ambient",
    )  # fmt: skip
    return DonationItem(**{**base, **kw})


def lot(b, **kw):
    base = dict(
        donation_item_id=b.item.id, category_id=b.protein.id, storage_type="ambient",
        received_lbs=100, remaining_lbs=100, expired_lbs=0, received_date=date(2026, 10, 1),
        status="available",
    )  # fmt: skip
    return InventoryLot(**{**base, **kw})


def pantry(**kw):
    base = dict(
        id=2, name="Pantry 02", county="Brookmere", latitude=40.2, longitude=-82.9,
        cold_capacity_lbs=1000, dry_capacity_lbs=1000, baseline_households=300,
    )  # fmt: skip
    return Pantry(**{**base, **kw})


def alloc(b, **kw):
    base = dict(
        allocation_run_id=b.alloc_run.id, lot_id=b.lot.id, pantry_id=b.pantry.id,
        recommended_lbs=50, reason="r", status="proposed",
    )  # fmt: skip
    return Allocation(**{**base, **kw})


def summary(**kw):
    base = dict(month=date(2026, 8, 1), aggregates={}, ai_draft="d", status="draft")
    return MonthlySummary(**{**base, **kw})


BAD_ROWS = {
    # --- negative / zero quantities -------------------------------------------------------
    "item quantity zero": lambda b: item(b, quantity=0),
    "item quantity negative": lambda b: item(b, quantity=-5),
    "item weight zero": lambda b: item(b, estimated_weight_lbs=0),
    "item weight negative": lambda b: item(b, estimated_weight_lbs=-1),
    "lot received zero": lambda b: lot(b, received_lbs=0, remaining_lbs=0),
    "lot received negative": lambda b: lot(b, received_lbs=-5, remaining_lbs=0),
    "lot remaining negative": lambda b: lot(b, remaining_lbs=-1),
    "lot remaining above received": lambda b: lot(b, remaining_lbs=150),
    "lot remaining plus expired above received": lambda b: lot(b, remaining_lbs=80, expired_lbs=30),
    "lot expired negative": lambda b: lot(b, expired_lbs=-1),
    "allocation lbs zero": lambda b: alloc(b, recommended_lbs=0),
    "allocation lbs negative": lambda b: alloc(b, recommended_lbs=-10),
    "allocation final negative": lambda b: alloc(b, final_lbs=-1),
    "distribution lbs negative": lambda b: Distribution(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 9, 21),
        lbs=-1,
        households=10,
    ),  # fmt: skip
    "distribution households negative": lambda b: Distribution(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 9, 21),
        lbs=5,
        households=-1,
    ),  # fmt: skip
    # --- unknown categories and other bad references --------------------------------------
    "category name not one of the eight": lambda b: Category(name="candy", perishable=False),
    "item with unknown category id": lambda b: item(b, category_id=999),
    "lot with unknown category id": lambda b: lot(b, category_id=999),
    "distribution with unknown category id": lambda b: Distribution(
        pantry_id=b.pantry.id, category_id=999, week_start=date(2026, 9, 21), lbs=5, households=1
    ),  # fmt: skip
    "distribution with unknown pantry": lambda b: Distribution(
        pantry_id=999, category_id=b.protein.id, week_start=date(2026, 9, 21), lbs=5, households=1
    ),  # fmt: skip
    "item with unknown donation": lambda b: item(b, donation_id=999),
    "allocation edit for unknown allocation": lambda b: AllocationEdit(
        allocation_id=999,
        user_id=b.coordinator.id,
        field="final_lbs",
        old_value="1",
        new_value="2",
    ),  # fmt: skip
    "user pointing at unknown pantry": lambda b: User(
        email="x@example.org",
        password_hash="h",
        full_name="X",
        role="pantry_manager",
        pantry_id=999,
    ),  # fmt: skip
    # --- enums ------------------------------------------------------------------------------
    "item storage type unknown": lambda b: item(b, storage_type="warm"),
    "lot storage type unknown": lambda b: lot(b, storage_type="warm"),
    "lot status unknown": lambda b: lot(b, status="lost"),
    "donation status unknown": lambda b: Donation(
        donor_id=b.donor.id, source_type="email", status="lost", received_at=NOW
    ),
    "donation source unknown": lambda b: Donation(
        donor_id=b.donor.id, source_type="fax", status="confirmed", received_at=NOW
    ),
    "donation latency negative": lambda b: Donation(
        donor_id=b.donor.id,
        source_type="pdf",
        status="confirmed",
        received_at=NOW,
        latency_ms=-5,
    ),  # fmt: skip
    "donor type unknown": lambda b: Donor(name="X", donor_type="bank"),
    "pantry county unknown": lambda b: pantry(county="Atlantis"),
    # decided_by/decided_at are filled in so only the status list can reject this row
    "allocation status unknown": lambda b: alloc(
        b, status="maybe", decided_by=b.coordinator.id, decided_at=NOW
    ),
    "allocation run status unknown": lambda b: AllocationRun(
        forecast_run_id=b.run.id, status="weird"
    ),
    "forecast run status unknown": lambda b: ForecastRun(
        model_name="lightgbm",
        train_start=date(2023, 1, 2),
        train_end=date(2023, 6, 5),
        horizon_week_start=MONDAY,
        status="weird",
    ),  # fmt: skip
    "summary status unknown": lambda b: summary(status="final"),
    # --- users ------------------------------------------------------------------------------
    "user role unknown": lambda b: User(
        email="x@example.org", password_hash="h", full_name="X", role="superuser"
    ),
    "pantry manager without a pantry": lambda b: User(
        email="x@example.org", password_hash="h", full_name="X", role="pantry_manager"
    ),
    "coordinator tied to a pantry": lambda b: User(
        email="x@example.org",
        password_hash="h",
        full_name="X",
        role="coordinator",
        pantry_id=b.pantry.id,
    ),  # fmt: skip
    "duplicate user email": lambda b: User(
        email="c@example.org", password_hash="h", full_name="X", role="admin"
    ),
    "user without password hash": lambda b: User(
        email="x@example.org", password_hash=None, full_name="X", role="admin"
    ),
    # --- pantries ---------------------------------------------------------------------------
    "pantry latitude out of range": lambda b: pantry(latitude=91),
    "pantry longitude out of range": lambda b: pantry(longitude=-181),
    "pantry cold capacity negative": lambda b: pantry(cold_capacity_lbs=-1),
    "pantry dry capacity negative": lambda b: pantry(dry_capacity_lbs=-1),
    "pantry households zero": lambda b: pantry(baseline_households=0),
    "duplicate pantry name": lambda b: pantry(name="Pantry 01"),
    # --- weeks and uniqueness ---------------------------------------------------------------
    "distribution week not a monday": lambda b: Distribution(
        pantry_id=b.pantry.id, category_id=b.protein.id, week_start=TUESDAY, lbs=5, households=1
    ),
    "duplicate distribution for pantry, category, week": lambda b: Distribution(
        pantry_id=b.pantry.id, category_id=b.protein.id, week_start=MONDAY, lbs=5, households=1
    ),
    "shortage severity zero": lambda b: ShortageReport(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 9, 21),
        severity=0,
        households_turned_away=1,
    ),  # fmt: skip
    "shortage severity four": lambda b: ShortageReport(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 9, 21),
        severity=4,
        households_turned_away=1,
    ),  # fmt: skip
    "shortage turned away negative": lambda b: ShortageReport(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 9, 21),
        severity=1,
        households_turned_away=-1,
    ),  # fmt: skip
    "shortage week not a monday": lambda b: ShortageReport(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=TUESDAY,
        severity=1,
        households_turned_away=0,
    ),  # fmt: skip
    "duplicate shortage for pantry, category, week": lambda b: ShortageReport(
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=MONDAY,
        severity=1,
        households_turned_away=0,
    ),  # fmt: skip
    "context precipitation negative": lambda b: WeeklyContext(
        county="Brookmere",
        week_start=MONDAY,
        avg_temp_f=50,
        precip_in=-1,
        school_holiday=False,
        benefit_week=False,
    ),  # fmt: skip
    "context county unknown": lambda b: WeeklyContext(
        county="Atlantis",
        week_start=MONDAY,
        avg_temp_f=50,
        precip_in=0,
        school_holiday=False,
        benefit_week=False,
    ),  # fmt: skip
    "duplicate context for county and week": lambda b: WeeklyContext(
        county="Ashford",
        week_start=MONDAY,
        avg_temp_f=50,
        precip_in=0,
        school_holiday=False,
        benefit_week=False,
    ),  # fmt: skip
    # --- forecasts --------------------------------------------------------------------------
    "forecast p10 above p50": lambda b: Forecast(
        forecast_run_id=b.run.id,
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 10, 5),
        p10_lbs=950,
        p50_lbs=900,
        p90_lbs=1200,
    ),  # fmt: skip
    "forecast p50 above p90": lambda b: Forecast(
        forecast_run_id=b.run.id,
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 10, 5),
        p10_lbs=700,
        p50_lbs=1300,
        p90_lbs=1200,
    ),  # fmt: skip
    "forecast negative": lambda b: Forecast(
        forecast_run_id=b.run.id,
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=date(2026, 10, 5),
        p10_lbs=-1,
        p50_lbs=5,
        p90_lbs=9,
    ),  # fmt: skip
    "duplicate forecast": lambda b: Forecast(
        forecast_run_id=b.run.id,
        pantry_id=b.pantry.id,
        category_id=b.protein.id,
        week_start=MONDAY,
        p10_lbs=1,
        p50_lbs=2,
        p90_lbs=3,
    ),  # fmt: skip
    "forecast run wape negative": lambda b: ForecastRun(
        model_name="lightgbm",
        wape_lightgbm=-0.1,
        train_start=date(2023, 1, 2),
        train_end=date(2023, 6, 5),
        horizon_week_start=MONDAY,
        status="completed",
    ),  # fmt: skip
    "forecast run trains backwards": lambda b: ForecastRun(
        model_name="lightgbm",
        train_start=date(2024, 1, 1),
        train_end=date(2023, 1, 1),
        horizon_week_start=MONDAY,
        status="completed",
    ),  # fmt: skip
    # --- allocation decisions and summaries -------------------------------------------------
    "proposed allocation already decided": lambda b: alloc(
        b, status="proposed", decided_by=b.coordinator.id, decided_at=NOW
    ),
    "approved allocation without decider": lambda b: alloc(
        b, status="approved", decided_at=NOW, final_lbs=50
    ),
    "approved allocation without timestamp": lambda b: alloc(
        b, status="approved", decided_by=b.coordinator.id, final_lbs=50
    ),
    "edit without a field name": lambda b: AllocationEdit(
        allocation_id=b.allocation.id,
        user_id=b.coordinator.id,
        field=None,
        old_value="1",
        new_value="2",
    ),  # fmt: skip
    "approved summary without approver": lambda b: summary(status="approved", final_text="t"),
    "approved summary without final text": lambda b: summary(
        status="approved", approved_by=b.coordinator.id, approved_at=NOW
    ),
    "draft summary already approved": lambda b: summary(
        status="draft", approved_by=b.coordinator.id, approved_at=NOW
    ),
    "summary month not the first": lambda b: summary(month=date(2026, 8, 15)),
    "duplicate summary month": lambda b: summary(month=date(2026, 9, 1)),
}


@pytest.mark.parametrize("make_row", BAD_ROWS.values(), ids=BAD_ROWS.keys())
def test_database_rejects_bad_data(session, b, make_row):
    session.add(make_row(b))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_decided_allocation_is_accepted(session, b):
    """The mirror of the rejection cases: a properly decided allocation goes in."""
    row = alloc(b, status="approved", decided_by=b.coordinator.id, decided_at=NOW, final_lbs=50)
    session.add(row)
    session.flush()
    assert row.id is not None


def test_approved_summary_with_approver_is_accepted(session, b):
    row = summary(
        status="approved", final_text="Final", approved_by=b.coordinator.id, approved_at=NOW
    )
    session.add(row)
    session.flush()
    assert row.id is not None
