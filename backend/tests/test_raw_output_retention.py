"""Raw model output is kept as audit evidence for 90 days after review, then cleared."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Donation, Donor
from app.services import retention
from tests.conftest import login

TODAY = date(2026, 10, 6)
RAW = {"tool_input": {"items": []}, "parsed": {"items": []}, "usage": {"input_tokens": 5}}
URL = "/api/admin/jobs/weekly-refresh"


def noon(days_ago: int) -> datetime:
    return datetime(2026, 10, 6, 12, tzinfo=UTC) - timedelta(days=days_ago)


@pytest.fixture
def donations(engine):
    """One donation per case; returns {name: id}."""
    cases = {
        "confirmed_old": ("confirmed", 91),
        "confirmed_recent": ("confirmed", 89),
        "rejected_old": ("rejected", 120),
        "rejected_recent": ("rejected", 10),
        "pending_old": ("pending_review", None),
    }
    ids = {}
    with Session(engine) as db:
        donor = Donor(name="Retention Donor", donor_type="grocery")
        db.add(donor)
        db.flush()
        for name, (status, reviewed_days_ago) in cases.items():
            d = Donation(
                source_type="email", status=status, raw_llm_output=RAW, model_id="m", latency_ms=5,
                received_at=noon(200), donor_id=donor.id if status == "confirmed" else None,
                reviewed_at=noon(reviewed_days_ago) if reviewed_days_ago is not None else None,
            )  # fmt: skip
            db.add(d)
            db.flush()
            ids[name] = d.id
        db.commit()
    yield ids
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM donations WHERE id = ANY(:ids)"), {"ids": list(ids.values())}
        )
        conn.execute(text("DELETE FROM donors WHERE name = 'Retention Donor'"))


def state(engine, ids):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, raw_llm_output IS NULL, raw_output_cleared_at, model_id, latency_ms "
                 "FROM donations WHERE id = ANY(:ids)"), {"ids": list(ids.values())},
        ).all()  # fmt: skip
    by_id = {r[0]: r for r in rows}
    return {name: by_id[i] for name, i in ids.items()}


def test_output_reviewed_more_than_90_days_ago_is_cleared(engine, donations):
    with Session(engine) as db:
        assert retention.clear_old_raw_output(db, TODAY) == 2
        db.commit()
    rows = state(engine, donations)
    for name in ("confirmed_old", "rejected_old"):
        assert rows[name][1] is True and rows[name][2] is not None, name
    assert rows["confirmed_old"][3:] == ("m", 5)  # model and latency are kept


def test_recent_and_unreviewed_output_is_kept(engine, donations):
    with Session(engine) as db:
        retention.clear_old_raw_output(db, TODAY)
        db.commit()
    rows = state(engine, donations)
    for name in ("confirmed_recent", "rejected_recent", "pending_old"):
        assert rows[name][1] is False and rows[name][2] is None, name


def test_a_second_run_clears_nothing_more_and_keeps_the_first_timestamp(engine, donations):
    with Session(engine) as db:
        retention.clear_old_raw_output(db, TODAY)
        db.commit()
    first = state(engine, donations)["confirmed_old"][2]
    with Session(engine) as db:
        assert retention.clear_old_raw_output(db, TODAY + timedelta(days=1)) == 0
        db.commit()
    assert state(engine, donations)["confirmed_old"][2] == first


def test_the_boundary_is_exactly_ninety_days(engine, donations):
    with Session(engine) as db:
        # two days earlier, the 91-day-old review is 89 days old: only the 120-day-old one goes
        assert retention.clear_old_raw_output(db, TODAY - timedelta(days=2)) == 1
        db.commit()
    assert state(engine, donations)["confirmed_old"][1] is False
    assert retention.RETENTION_DAYS == 90


def test_the_database_refuses_a_cleared_marker_on_a_donation_that_still_has_output(
    engine, donations
):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE donations SET raw_output_cleared_at = now() WHERE id = :i"),
                     {"i": donations["confirmed_recent"]})  # fmt: skip


def test_the_database_refuses_clearing_a_pending_donation(engine, donations):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE donations SET raw_llm_output = NULL, raw_output_cleared_at = now() "
                          "WHERE id = :i"), {"i": donations["pending_old"]})  # fmt: skip


@pytest.mark.usefixtures("people", "forecast_data", "allocation_world")
def test_the_weekly_refresh_clears_old_output_and_reports_how_many(
    client, people, engine, donations, llm
):
    from app.ai.llm_provider import LLMTimeout

    llm.script(LLMTimeout("slow"))
    login(client, people.admin)
    response = client.post(URL)
    assert response.status_code == 200, response.text
    assert response.json()["raw_outputs_cleared"] == 2
    assert state(engine, donations)["confirmed_old"][1] is True


def test_the_retention_period_is_documented():
    from tests.conftest import BACKEND_DIR

    text_ = (BACKEND_DIR.parent / "docs/security/audit.md").read_text()
    assert "90 days" in text_ and "raw_output_cleared_at" in text_


def test_a_cleared_donation_still_opens_and_says_its_output_was_cleared(client, people, donations):
    with_engine = client.app.state.engine
    with Session(with_engine) as db:
        retention.clear_old_raw_output(db, TODAY)
        db.commit()
    login(client, people.coordinator)
    cleared = client.get(f"/api/donations/{donations['rejected_old']}")
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["raw_output_cleared_at"] is not None and body["items"] == []
    kept = client.get(f"/api/donations/{donations['rejected_recent']}").json()
    assert kept["raw_output_cleared_at"] is None
