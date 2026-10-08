"""Server-side validation for the forms that had no dedicated test: every bad input is a 422 in
the one error envelope, with a message per field, and nothing is saved."""

import pytest

from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people", "impact_world")


@pytest.fixture
def admin(client, people):
    login(client, people.admin)
    return client


def assert_envelope(response, field=None):
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error" and error["message"]
    if field:
        assert field in [d["field"] for d in error["details"]]


@pytest.mark.parametrize(
    "params, field",
    [
        ({"start": "not-a-date"}, "start"),
        ({"end": "2026-13-45"}, "end"),
        ({"start": "2000-01-03", "end": "2026-09-14"}, "start"),  # more than 260 weeks
        ({"start": "2026-09-14", "end": "2026-09-07"}, "start"),
    ],
)
def test_dashboard_range_rejects_bad_dates(admin, params, field):
    assert_envelope(admin.get("/api/dashboard/metrics", params=params), field)


@pytest.mark.parametrize("body", [{"ids": []}, {"ids": ["a"]}, {"ids": list(range(1001))}, {}])
def test_bulk_approve_rejects_bad_id_lists(admin, body):
    assert_envelope(admin.post("/api/allocations/bulk-approve", json=body))


@pytest.mark.parametrize("params", [{"status": "done"}, {"week_start": "tomorrow"}])
def test_allocation_list_rejects_bad_filters(admin, params):
    assert_envelope(admin.get("/api/allocations", params=params))


@pytest.mark.parametrize("body", [{"lbs": "lots"}, {"lbs": 5, "note": 5}, {"note": "x"}])
def test_allocation_edit_rejects_bad_bodies(admin, body):
    assert_envelope(admin.post("/api/allocations/1/edit", json=body))


@pytest.mark.parametrize(
    "body",
    [{}, {"email": "a@b.co"}, {"email": "nope", "password": "x"}, {"email": "a@b.co", "password": ""},
     {"email": "a@b.co", "password": "x" * 201}, {"email": "a" * 250 + "@b.co", "password": "x"}],
)  # fmt: skip
def test_login_rejects_bad_bodies(client, body):
    assert_envelope(client.post("/api/auth/login", json=body))


@pytest.mark.parametrize(
    "path", ["/api/forecasts?week_start=2026-09-08", "/api/forecasts?category=candy"]
)
def test_forecast_filters_are_validated(admin, path):
    assert_envelope(admin.get(path))


def test_summary_text_over_the_limit_is_refused_and_nothing_is_saved(admin, engine):
    assert_envelope(
        admin.post("/api/dashboard/summaries/2026-09/approve", json={"text": "x" * 4001}), "text"
    )
    from sqlalchemy import text

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM monthly_summaries")).scalar() == 0
