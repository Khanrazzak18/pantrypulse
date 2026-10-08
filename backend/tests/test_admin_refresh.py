"""POST /api/admin/jobs/weekly-refresh: forecast, then allocation, admin only, under 20 s."""

import time

import pytest
from sqlalchemy import text

from app.ai.llm_provider import LLMTimeout
from tests.conftest import login

URL = "/api/admin/jobs/weekly-refresh"


@pytest.fixture(autouse=True)
def reasons_down(llm):
    llm.script(LLMTimeout("slow"))


@pytest.fixture
def admin(client, people):
    login(client, people.admin)
    return client


def count(engine, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


@pytest.mark.usefixtures("people", "forecast_data", "allocation_world")
def test_refresh_trains_the_forecast_then_allocates(admin, engine):
    started = time.monotonic()
    response = admin.post(URL)
    assert time.monotonic() - started < 20
    assert response.status_code == 200, response.text
    out = response.json()
    assert [s["name"] for s in out["steps"]] == ["forecast", "allocation"]
    assert all(s["status"] == "done" and s["seconds"] >= 0 for s in out["steps"])
    assert out["forecast_run_id"] and out["allocation_run_id"] and out["week_start"] == "2026-10-05"
    assert count(engine, "SELECT count(*) FROM forecast_runs WHERE kind='forward'") == 2
    assert count(engine, "SELECT count(*) FROM allocation_runs") == 1
    run_forecast_id = count(engine, "SELECT forecast_run_id FROM allocation_runs")
    assert run_forecast_id == out["forecast_run_id"]  # allocated against the forecast just made


@pytest.mark.usefixtures("people", "forecast_data")
def test_a_failed_forecast_stops_before_allocation(admin, engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM distributions"))
    response = admin.post(URL)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_enough_history"
    assert count(engine, "SELECT count(*) FROM allocation_runs") == 0


@pytest.mark.usefixtures("people", "forecast_data")
def test_a_failed_allocation_keeps_the_new_forecast_and_says_so(admin, engine):
    response = admin.post(URL)  # no stock at all
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["code"] == "refresh_partial"
    assert "forecast was saved" in err["message"].lower()
    assert err["details"]["forecast_run_id"] and err["details"]["cause"] == "no_inventory"
    assert count(engine, "SELECT count(*) FROM forecast_runs WHERE kind='forward'") == 1


@pytest.mark.usefixtures("people")
def test_only_admins_run_the_refresh(client, people, engine):
    assert client.post(URL).status_code == 401
    for email in (people.coordinator, people.manager):
        client.cookies.clear()
        login(client, email)
        assert client.post(URL).status_code == 403
    assert count(engine, "SELECT count(*) FROM forecast_runs") == 0
