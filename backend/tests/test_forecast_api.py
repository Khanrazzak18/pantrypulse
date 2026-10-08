"""POST /api/forecasts/run and the read endpoints: permissions, filters, saving, failure paths."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from app.constants import CATEGORY_NAMES
from app.services import forecast_runs, forecasting
from tests.conftest import login, row_count

pytestmark = pytest.mark.usefixtures("people", "forecast_data")
SERIES = 3 * 2  # 3 pantries x 2 categories


@pytest.fixture
def coordinator(client, people):
    login(client, people.coordinator)
    return client


def run(client):
    return client.post("/api/forecasts/run")


def query(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def make_backtest(db_engine, storage, app, weeks=8):
    from sqlalchemy.orm import Session

    config = app.state.forecast_config
    with Session(db_engine) as db:
        panel = forecast_runs.load_panel(db)
        result = forecasting.run_backtest(panel, config, weeks=weeks)
        return forecast_runs.save_backtest(db, storage, result, panel).id


# --- running a forecast -----------------------------------------------------------------------------


def test_a_run_trains_once_and_saves_next_weeks_forecast(
    coordinator, forecast_data, migrated_engine, storage
):
    response = run(coordinator)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "forward" and body["status"] == "completed"
    assert body["horizon_week_start"] == forecast_data.next.isoformat()
    assert body["train_end"] == forecast_data.last.isoformat() and body["rows"] == SERIES
    assert body["wape_lightgbm"] is None  # accuracy comes from the backtest, not from this run
    assert body["backtest_end"] is None  # only backtests have a scored period

    rows = query(migrated_engine, "SELECT week_start, p10_lbs, p50_lbs, p90_lbs FROM forecasts")
    assert len(rows) == SERIES and {r[0] for r in rows} == {forecast_data.next}
    assert all(r[1] <= r[2] <= r[3] for r in rows)
    key = (
        body["model_key"]
        if "model_key" in body
        else query(migrated_engine, "SELECT model_key FROM forecast_runs")[0][0]
    )
    assert all(
        storage.exists(f"{key}/{name}") for name in ("p10.txt", "p50.txt", "p90.txt", "meta.json")
    )


def test_the_saved_models_can_be_loaded_back_and_predict(coordinator, migrated_engine, storage):
    run(coordinator)
    (key,) = query(migrated_engine, "SELECT model_key FROM forecast_runs")[0]
    models = forecasting.load_models(storage, key)
    assert models.features == forecasting.FEATURES and set(models.boosters) == {"p10", "p50", "p90"}


def test_running_twice_makes_two_runs_and_the_latest_is_used(coordinator, migrated_engine):
    first = run(coordinator).json()["id"]
    second = run(coordinator).json()["id"]
    assert second > first and row_count(migrated_engine, "forecast_runs") == 2
    rows = coordinator.get("/api/forecasts").json()
    assert {r["run_id"] for r in rows} == {second}


def test_a_run_is_refused_when_there_is_too_little_history(coordinator, migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM distributions WHERE week_start < '2026-07-01'"))
    response = run(coordinator)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "not_enough_history" and "30 weeks" in error["message"]
    assert error["details"]["needed"] == 30 and error["details"]["found"] < 30
    assert row_count(migrated_engine, "forecast_runs") == 0  # not a failure, so no run is recorded


def test_a_run_with_no_data_at_all_says_so(coordinator, migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM distributions"))
    assert run(coordinator).json()["error"]["code"] == "not_enough_history"


def test_a_run_that_is_already_in_progress_blocks_a_second_one(coordinator, migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO forecast_runs (model_name, kind, status, train_start, train_end, "
                "horizon_week_start) VALUES ('lightgbm', 'forward', 'running', '2023-10-02', "
                "'2026-09-28', '2026-10-05')"
            )
        )
    response = run(coordinator)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "forecast_in_progress"
    )


def test_a_stale_running_row_does_not_block_new_runs(coordinator, migrated_engine):
    old = datetime.now(UTC) - timedelta(minutes=forecast_runs.STALE_AFTER.seconds // 60 + 5)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO forecast_runs (model_name, kind, status, train_start, train_end, "
                "horizon_week_start, created_at) VALUES ('lightgbm', 'forward', 'running', "
                "'2023-10-02', '2026-09-28', '2026-10-05', :old)"
            ),
            {"old": old},
        )
    assert run(coordinator).status_code == 201


def test_a_model_failure_is_recorded_and_reported_without_internals(
    coordinator, migrated_engine, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(forecasting, "forward_forecast", boom)
    response = run(coordinator)
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "forecast_failed" and "secret internal detail" not in response.text
    ((status, message),) = query(migrated_engine, "SELECT status, error_message FROM forecast_runs")
    assert status == "failed" and "secret internal detail" in message
    assert row_count(migrated_engine, "forecasts") == 0


# --- permissions --------------------------------------------------------------------------------------

READ_PATHS = [
    "/api/forecasts",
    "/api/forecasts/runs/latest",
    "/api/forecasts/series?pantry_id=911&category=produce",
]


@pytest.mark.parametrize("path", READ_PATHS)
def test_logged_out_users_get_401_on_every_read(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", READ_PATHS)
def test_pantry_managers_get_403_on_every_read(client, people, path):
    login(client, people.manager)
    assert client.get(path).status_code == 403


def test_run_permissions(client, people):
    assert run(client).status_code == 401
    login(client, people.manager)
    assert run(client).status_code == 403
    login(client, people.admin)
    assert run(client).status_code == 201


# --- reading forecasts ------------------------------------------------------------------------------


@pytest.fixture
def ran(coordinator):
    assert run(coordinator).status_code == 201
    return coordinator


def test_forecasts_come_back_with_names_and_no_actuals_for_the_future(ran, forecast_data):
    rows = ran.get("/api/forecasts").json()
    assert len(rows) == SERIES
    first = rows[0]
    assert set(first) == {"run_id", "pantry_id", "pantry_name", "category", "week_start",
                          "p10_lbs", "p50_lbs", "p90_lbs", "baseline_lbs", "actual_lbs"}  # fmt: skip
    assert first["actual_lbs"] is None and first["week_start"] == forecast_data.next.isoformat()
    # ordered by pantry, then in the usual food-type order (produce, dairy, ...), not alphabetically
    order = [(r["pantry_id"], CATEGORY_NAMES.index(r["category"])) for r in rows]
    assert order == sorted(order)


def test_filter_by_pantry(ran):
    rows = ran.get("/api/forecasts", params={"pantry_id": 912}).json()
    assert len(rows) == 2 and {r["pantry_id"] for r in rows} == {912}


def test_filter_by_category(ran):
    rows = ran.get("/api/forecasts", params={"category": "dairy"}).json()
    assert len(rows) == 3 and {r["category"] for r in rows} == {"dairy"}


def test_filter_by_week(ran, forecast_data):
    assert (
        len(ran.get("/api/forecasts", params={"week_start": forecast_data.next.isoformat()}).json())
        == SERIES
    )
    assert (
        ran.get("/api/forecasts", params={"week_start": forecast_data.last.isoformat()}).json()
        == []
    )


def test_filters_combine(ran):
    rows = ran.get("/api/forecasts", params={"pantry_id": 913, "category": "produce"}).json()
    assert len(rows) == 1 and rows[0]["pantry_name"] == "Forecast Pantry 3"


def test_unknown_pantry_gives_an_empty_list_and_bad_filters_are_rejected(ran):
    assert ran.get("/api/forecasts", params={"pantry_id": 424242}).json() == []
    assert ran.get("/api/forecasts", params={"category": "candy"}).status_code == 422
    assert ran.get("/api/forecasts", params={"kind": "nightly"}).status_code == 422
    assert ran.get("/api/forecasts", params={"limit": 0}).status_code == 422
    bad_week = ran.get("/api/forecasts", params={"week_start": "2026-10-06"})  # a Tuesday
    assert (
        bad_week.status_code == 422
        and bad_week.json()["error"]["details"][0]["field"] == "week_start"
    )


def test_before_any_run_the_list_is_empty(coordinator):
    assert coordinator.get("/api/forecasts").json() == []
    assert coordinator.get("/api/forecasts", params={"kind": "backtest"}).json() == []


def test_a_specific_run_can_be_asked_for(coordinator):
    first = run(coordinator).json()["id"]
    run(coordinator)
    rows = coordinator.get("/api/forecasts", params={"run_id": first}).json()
    assert {r["run_id"] for r in rows} == {first}
    assert coordinator.get("/api/forecasts", params={"run_id": 424242}).status_code == 404


# --- backtest runs ------------------------------------------------------------------------------------


def test_a_saved_backtest_carries_its_metrics_and_actuals(
    coordinator, app, migrated_engine, storage, forecast_data
):
    run_id = make_backtest(migrated_engine, storage, app, weeks=8)
    latest = coordinator.get("/api/forecasts/runs/latest").json()
    backtest = latest["backtest"]
    assert backtest["id"] == run_id and backtest["kind"] == "backtest" and latest["forward"] is None
    assert 0 <= backtest["wape_lightgbm"] < 1 and backtest["wape_baseline"] is not None
    assert 0 <= backtest["coverage_p10_p90"] <= 1 and backtest["rows"] == 8 * SERIES
    first_origin = forecast_data.weeks[-8]
    assert backtest["backtest_start"] == first_origin.isoformat()
    # the last week that was forecast and scored (one after the last week the model trained on)
    assert backtest["backtest_end"] == forecast_data.last.isoformat()
    assert backtest["train_end"] == forecast_data.weeks[-2].isoformat()

    rows = coordinator.get(
        "/api/forecasts", params={"kind": "backtest", "pantry_id": 911, "category": "produce"}
    ).json()
    assert len(rows) == 8 and all(r["actual_lbs"] is not None for r in rows)
    assert [r["week_start"] for r in rows] == [w.isoformat() for w in forecast_data.weeks[-8:]]


def test_latest_runs_reports_nothing_before_any_run(coordinator):
    assert coordinator.get("/api/forecasts/runs/latest").json() == {
        "backtest": None,
        "forward": None,
    }


def test_a_forward_run_does_not_replace_the_latest_backtests_metrics(
    coordinator, app, migrated_engine, storage
):
    make_backtest(migrated_engine, storage, app, weeks=8)
    run(coordinator)
    latest = coordinator.get("/api/forecasts/runs/latest").json()
    assert (
        latest["backtest"]["wape_lightgbm"] is not None and latest["forward"]["kind"] == "forward"
    )


# --- the chart series ---------------------------------------------------------------------------------


def series(client, **params):
    return client.get(
        "/api/forecasts/series", params={"pantry_id": 911, "category": "produce", **params}
    )


def test_the_series_has_history_then_the_forecast_week(ran, forecast_data):
    body = series(ran, history_weeks=10).json()
    points = body["points"]
    assert body["pantry_name"] == "Forecast Pantry 1" and body["category"] == "produce"
    assert [p["week_start"] for p in points][:-1] == [
        w.isoformat() for w in forecast_data.weeks[-10:]
    ]
    assert points[-1]["week_start"] == forecast_data.next.isoformat()
    assert points[-1]["actual_lbs"] is None and points[-1]["source"] == "forward"
    assert points[-1]["p10_lbs"] <= points[-1]["p50_lbs"] <= points[-1]["p90_lbs"]
    assert all(p["actual_lbs"] is not None and p["source"] is None for p in points[:-1])
    assert body["accuracy"] is None  # no backtest yet


def test_the_series_overlays_backtest_forecasts_and_scores_them(
    ran, app, migrated_engine, storage, forecast_data
):
    make_backtest(migrated_engine, storage, app, weeks=8)
    body = series(ran, history_weeks=20).json()
    tested = [p for p in body["points"] if p["source"] == "backtest"]
    assert len(tested) == 8 and all(
        p["p50_lbs"] is not None and p["actual_lbs"] is not None for p in tested
    )
    assert body["accuracy"]["weeks_scored"] == 8
    assert (
        0 <= body["accuracy"]["wape_lightgbm"] < 1 and body["accuracy"]["wape_baseline"] is not None
    )


def test_the_series_without_a_forecast_still_shows_history(coordinator):
    body = series(coordinator, history_weeks=6).json()
    assert len(body["points"]) == 6 and all(p["p50_lbs"] is None for p in body["points"])


def test_series_inputs_are_validated(coordinator):
    assert coordinator.get("/api/forecasts/series").status_code == 422
    assert coordinator.get("/api/forecasts/series", params={"pantry_id": 911}).status_code == 422
    assert series(coordinator, category="candy").status_code == 422
    assert series(coordinator, history_weeks=2).status_code == 422
    unknown = coordinator.get(
        "/api/forecasts/series", params={"pantry_id": 424242, "category": "dairy"}
    )
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "not_found"


# --- load_panel ---------------------------------------------------------------------------------------


def test_load_panel_returns_one_row_per_series_and_week_with_context(
    migrated_engine, forecast_data
):
    from sqlalchemy.orm import Session

    with Session(migrated_engine) as db:
        panel = forecast_runs.load_panel(db)
    assert len(panel) == SERIES * 70 and panel.week_start.nunique() == 70
    assert panel.severity.notna().sum() == 2
    one = panel[(panel.pantry_id == 911) & (panel.category_id == 1)].sort_values("week_start")
    assert (
        one.county.iloc[0] == "Ashford"
        and one.temp.notna().all()
        and one.school_holiday.notna().all()
    )
    assert pd.api.types.is_datetime64_any_dtype(panel.week_start)
    assert date(2026, 9, 28) == panel.week_start.max().date()
