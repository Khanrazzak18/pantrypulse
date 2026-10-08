"""Incoming deliveries for a pantry manager: only their own pantry, only approved ones."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Allocation, AllocationRun, User
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people", "allocation_world")


@pytest.fixture
def deliveries(migrated_engine, people, allocation_world):
    """Rows for pantry 901 (the manager's) and 902, in three runs. Today is 2026-10-06."""
    lots = allocation_world.lots

    def run(db, week, delivery, user):
        r = AllocationRun(
            forecast_run_id=allocation_world.forecast_run_id, created_by=user.id, status="draft",
            week_start=week, delivery_date=delivery,
        )  # fmt: skip
        db.add(r)
        db.flush()
        return r

    def row(db, r, lot, pantry, status, user, final=None, delivery=None):
        decided = status != "proposed"
        db.add(
            Allocation(
                allocation_run_id=r.id,
                lot_id=lots[lot],
                pantry_id=pantry,
                recommended_lbs=100,
                reason="r",
                reason_source="template",
                status=status,
                final_lbs=final,
                decided_by=user.id if decided else None,
                decided_at=datetime(2026, 10, 6, tzinfo=UTC) if decided else None,
                delivery_date=delivery,
            )  # fmt: skip
        )

    with Session(migrated_engine) as db:
        user = db.query(User).filter_by(email=people.coordinator).one()
        now = run(db, date(2026, 10, 5), date(2026, 10, 6), user)
        row(db, now, "A", 901, "approved", user, 100, date(2026, 10, 6))
        row(db, now, "B", 901, "edited", user, 50, date(2026, 10, 7))
        row(db, now, "C", 901, "proposed", user)
        row(db, now, "D", 901, "rejected", user)
        row(db, now, "A", 902, "approved", user, 77, date(2026, 10, 6))
        last = run(db, date(2026, 9, 28), date(2026, 9, 30), user)
        row(db, last, "B", 901, "approved", user, 30, date(2026, 9, 30))
        old = run(db, date(2026, 9, 14), date(2026, 9, 15), user)
        row(db, old, "C", 901, "approved", user, 20, date(2026, 9, 15))
        db.commit()


@pytest.fixture
def manager(client, people):
    login(client, people.manager)
    return client


def test_a_manager_sees_only_their_pantrys_approved_deliveries(manager, deliveries):
    out = manager.get("/api/pantry/deliveries").json()
    assert out["pantry"]["id"] == 901
    upcoming = [(d["final_lbs"], d["delivery_date"]) for d in out["upcoming"]]
    assert upcoming == [(100, "2026-10-06"), (50, "2026-10-07")]  # earliest first, none of 902's
    assert [(d["final_lbs"], d["delivery_date"]) for d in out["recent"]] == [(30, "2026-09-30")]


def test_proposed_and_rejected_rows_are_never_shown(manager, deliveries):
    out = manager.get("/api/pantry/deliveries").json()
    assert 77 not in [d["final_lbs"] for d in out["upcoming"] + out["recent"]]
    assert len(out["upcoming"]) + len(out["recent"]) == 3


def test_a_delivery_carries_category_lbs_date_and_expiry(manager, deliveries):
    first = manager.get("/api/pantry/deliveries").json()["upcoming"][0]
    assert first["category"] == "produce"
    assert first["item_name"] and first["expiry_date"] == "2026-10-09"
    assert set(first) >= {"id", "category", "final_lbs", "delivery_date", "expiry_date", "edited"}


def test_deliveries_older_than_a_week_drop_off(manager, deliveries):
    dates = [d["delivery_date"] for d in manager.get("/api/pantry/deliveries").json()["recent"]]
    assert "2026-09-15" not in dates


def test_no_deliveries_is_an_empty_page_not_an_error(manager):
    out = manager.get("/api/pantry/deliveries").json()
    assert out["upcoming"] == [] and out["recent"] == []


def test_the_other_pantrys_manager_sees_their_own(
    client, deliveries, migrated_engine, password_hash
):
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, password_hash, full_name, role, pantry_id, is_active) "
                "VALUES ('m2@example.org', :h, 'M Two', 'pantry_manager', 902, true)"
            ),
            {"h": password_hash},
        )
    try:
        login(client, "m2@example.org")
        out = client.get("/api/pantry/deliveries").json()
        assert out["pantry"]["id"] == 902
        assert [d["final_lbs"] for d in out["upcoming"]] == [77]
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE email = 'm2@example.org'"))


def test_only_pantry_managers_use_the_portal(client, people):
    assert client.get("/api/pantry/deliveries").status_code == 401
    for email in (people.coordinator, people.admin):
        client.cookies.clear()
        login(client, email)
        assert client.get("/api/pantry/deliveries").status_code == 403
