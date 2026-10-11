"""Database-backed rate limits on uploads and every expensive or AI endpoint, per user and per hour.
Each limit is configurable in .env; each has a test that proves it triggers."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.main import create_app
from tests.conftest import login
from tests.fakes import FakeLLM

pytestmark = pytest.mark.usefixtures("people")

# scope -> (method, url, how the request is sent). Every request counts, whatever it returns.
LIMITED = {
    "uploads": ("POST", "/api/donations", "file"),
    "allocation_run": ("POST", "/api/allocations/run", None),
    "allocation_reasons": ("POST", "/api/allocations/runs/1/reasons", None),
    "summary_draft": ("POST", "/api/dashboard/summaries/2026-09/draft", None),
    "forecast_run": ("POST", "/api/forecasts/run", None),
    "weekly_refresh": ("POST", "/api/admin/jobs/weekly-refresh", None),
}
SETTING = {
    "uploads": "rate_limit_uploads_per_hour",
    "weekly_refresh": "rate_limit_refresh_per_hour",
}


def limit_setting(scope):
    return SETTING.get(scope, "rate_limit_ai_per_hour")


@pytest.fixture
def limited_app(settings, engine):
    def make(**limits):
        app = create_app(settings.model_copy(update=limits), engine, llm=FakeLLM())
        return TestClient(app, raise_server_exceptions=False)

    return make


def send(client, scope):
    method, url, kind = LIMITED[scope]
    if kind == "file":
        return client.request(method, url, files={"file": ("a.txt", b"", "text/plain")})
    return client.request(method, url)


@pytest.fixture(autouse=True)
def clean(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE rate_limits"))
    yield
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE rate_limits"))


def test_the_defaults_are_the_documented_ones():
    s = Settings()
    assert (
        s.rate_limit_uploads_per_hour,
        s.rate_limit_ai_per_hour,
        s.rate_limit_refresh_per_hour,
    ) == (20, 30, 6)


@pytest.mark.parametrize("scope", list(LIMITED))
def test_each_limit_triggers_after_its_configured_number_of_requests(limited_app, people, scope):
    client = limited_app(**{limit_setting(scope): 2})
    login(client, people.admin)
    for _ in range(2):
        assert send(client, scope).status_code != 429
    blocked = send(client, scope)
    assert blocked.status_code == 429
    error = blocked.json()["error"]
    assert error["code"] == "rate_limited" and error["request_id"]
    assert int(blocked.headers["retry-after"]) > 0
    assert "try again" in error["message"].lower()


@pytest.mark.parametrize("scope", list(LIMITED))
def test_a_limit_of_zero_blocks_the_first_request(limited_app, people, scope):
    client = limited_app(**{limit_setting(scope): 0})
    login(client, people.admin)
    assert send(client, scope).status_code == 429


def test_limits_are_per_user(limited_app, people, settings, engine):
    one = limited_app(rate_limit_uploads_per_hour=1)
    login(one, people.admin)
    send(one, "uploads")
    assert send(one, "uploads").status_code == 429
    other = limited_app(rate_limit_uploads_per_hour=1)
    login(other, people.coordinator)
    assert send(other, "uploads").status_code != 429


def test_limits_are_per_endpoint(limited_app, people):
    client = limited_app(rate_limit_uploads_per_hour=1, rate_limit_ai_per_hour=5)
    login(client, people.admin)
    send(client, "uploads")
    assert send(client, "uploads").status_code == 429
    assert send(client, "allocation_run").status_code != 429  # a different counter


def test_the_counter_lives_in_the_database_so_every_instance_shares_it(limited_app, people):
    first = limited_app(rate_limit_uploads_per_hour=1)
    login(first, people.admin)
    send(first, "uploads")
    second = limited_app(rate_limit_uploads_per_hour=1)  # a different "instance"
    login(second, people.admin)
    assert send(second, "uploads").status_code == 429


def test_the_window_resets_after_an_hour(limited_app, people, engine):
    client = limited_app(rate_limit_uploads_per_hour=1)
    login(client, people.admin)
    send(client, "uploads")
    assert send(client, "uploads").status_code == 429
    with engine.begin() as conn:
        conn.execute(text("UPDATE rate_limits SET window_start = now() - interval '61 minutes'"))
    assert send(client, "uploads").status_code != 429


def test_a_logged_out_caller_is_refused_before_anything_is_counted(limited_app, engine):
    client = limited_app(rate_limit_uploads_per_hour=1)
    assert send(client, "uploads").status_code == 401
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM rate_limits")).scalar() == 0


def test_the_table_stores_hashes_not_user_ids(limited_app, people, engine):
    client = limited_app()
    login(client, people.admin)
    send(client, "uploads")
    with engine.connect() as conn:
        keys = [r[0] for r in conn.execute(text("SELECT key_hash FROM rate_limits"))]
    assert keys and all(len(k) == 64 for k in keys)


def test_a_limit_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_UPLOADS_PER_HOUR", "3")
    monkeypatch.setenv("RATE_LIMIT_AI_PER_HOUR", "4")
    monkeypatch.setenv("RATE_LIMIT_REFRESH_PER_HOUR", "5")
    s = Settings()
    assert (
        s.rate_limit_uploads_per_hour,
        s.rate_limit_ai_per_hour,
        s.rate_limit_refresh_per_hour,
    ) == (3, 4, 5)
