"""Shortage reports from the pantry portal: validation, the current week, update on duplicate."""

from datetime import date

import pytest
from sqlalchemy import text

from tests.conftest import PANTRY_A, login

pytestmark = pytest.mark.usefixtures("people")
WEEK = "2026-10-05"  # the app fixture pins today to Tuesday 2026-10-06


@pytest.fixture
def manager(client, people):
    login(client, people.manager)
    return client


def report(client, **overrides):
    body = {
        "category": "produce",
        "severity": 2,
        "households_turned_away": 5,
        "note": "Ran out Friday",
    }
    return client.post("/api/pantry/shortage-reports", json={**body, **overrides})


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT pantry_id, category_id, week_start, severity, households_turned_away, notes, "
                "reported_by FROM shortage_reports ORDER BY id"
            )
        ).all()


@pytest.fixture(autouse=True)
def clean(migrated_engine):
    yield
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE shortage_reports RESTART IDENTITY"))


def test_a_report_is_saved_for_this_week_and_the_managers_own_pantry(manager, engine):
    response = report(manager)
    assert response.status_code == 201
    out = response.json()
    assert out["week_start"] == WEEK and out["category"] == "produce" and out["updated"] is False
    (row,) = rows(engine)
    assert row[0] == PANTRY_A and row[1] == 1 and row[2] == date(2026, 10, 5)
    assert row[3:6] == (2, 5, "Ran out Friday") and row[6] is not None


def test_the_pantry_cannot_be_chosen_by_the_caller(manager, engine):
    report(manager, pantry_id=902)
    assert rows(engine)[0][0] == PANTRY_A


def test_a_second_report_updates_the_first(manager, engine):
    assert report(manager).status_code == 201
    second = report(manager, severity=3, households_turned_away=12, note="Now fully out")
    assert second.status_code == 200 and second.json()["updated"] is True
    (row,) = rows(engine)
    assert row[3:6] == (3, 12, "Now fully out")


def test_different_categories_are_separate_reports(manager, engine):
    report(manager)
    report(manager, category="dairy")
    assert len(rows(engine)) == 2


def test_this_weeks_reports_can_be_listed_for_prefilling_the_form(manager):
    report(manager)
    report(manager, category="dairy", severity=1)
    listed = manager.get("/api/pantry/shortage-reports").json()
    assert {r["category"]: r["severity"] for r in listed} == {"produce": 2, "dairy": 1}


def test_other_pantries_reports_are_not_listed(manager, client, people, engine):
    report(manager)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO shortage_reports (pantry_id, category_id, week_start, severity, "
                "households_turned_away) VALUES (902, 2, '2026-10-05', 1, 0)"
            )
        )
    assert [r["category"] for r in manager.get("/api/pantry/shortage-reports").json()] == [
        "produce"
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"severity": 0},
        {"severity": 4},
        {"category": "candy"},
        {"households_turned_away": -1},
        {"households_turned_away": 10_000_000},
        {"note": "x" * 501},
        {"severity": "high"},
    ],
)
def test_invalid_reports_are_refused_with_field_messages(manager, engine, overrides):
    response = report(manager, **overrides)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert rows(engine) == []


def test_note_and_turned_away_are_optional(manager, engine):
    response = manager.post(
        "/api/pantry/shortage-reports", json={"category": "protein", "severity": 1}
    )
    assert response.status_code == 201
    assert rows(engine)[0][4:6] == (0, None)


def test_a_blank_note_is_stored_as_nothing(manager, engine):
    report(manager, note="   ")
    assert rows(engine)[0][5] is None


def test_only_pantry_managers_report(client, people):
    assert report(client).status_code == 401
    for email in (people.coordinator, people.admin):
        client.cookies.clear()
        login(client, email)
        assert report(client).status_code == 403


def test_the_report_reaches_the_forecast_panel_once_the_week_has_distributions(
    manager, engine, migrated_engine
):
    from sqlalchemy.orm import Session

    from app.services import forecast_runs

    report(manager, severity=3, households_turned_away=9)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO distributions (pantry_id, category_id, week_start, lbs, households) "
                "VALUES (901, 1, '2026-10-05', 100, 50)"
            )
        )
    try:
        with Session(migrated_engine) as db:
            panel = forecast_runs.load_panel(db)
        row = panel[(panel.pantry_id == PANTRY_A) & (panel.category_id == 1)].iloc[0]
        assert row.severity == 3 and row.turned_away == 9
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text("DELETE FROM distributions WHERE pantry_id = 901"))
