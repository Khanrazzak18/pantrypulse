"""Regression tests for the Stage 10 bugs (docs/testing/bugs.md): each was a 500 or a wrong answer."""

import pytest

from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people")
HUGE = 99999999999999999999
OVER_INT = 2_147_483_648


@pytest.fixture
def admin(client, people):
    login(client, people.admin)
    return client


def envelope(response, status):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert {"code", "message", "details", "request_id"} <= set(error)
    return error


# --- BUG-01: ids larger than the database allows are a 404 -----------------------------------


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/donations/{id}"),
        ("POST", "/api/donations/{id}/confirm"),
        ("POST", "/api/donations/{id}/reject"),
        ("GET", "/api/pantries/{id}"),
        ("POST", "/api/allocations/{id}/approve"),
        ("POST", "/api/allocations/{id}/reject"),
        ("POST", "/api/allocations/{id}/edit"),
        ("POST", "/api/allocations/runs/{id}/reasons"),
    ],
)
@pytest.mark.parametrize("bad", [OVER_INT, HUGE, 0, -1])
def test_bug_01_out_of_range_ids_are_a_404_in_the_envelope(admin, method, path, bad):
    body = {"lbs": 5, "items": [], "donor_name": "x"} if method == "POST" else None
    error = envelope(admin.request(method, path.format(id=bad), json=body), 404)
    assert error["code"] == "not_found"


def test_bug_01_the_largest_valid_id_is_an_ordinary_404_for_a_missing_row(admin):
    assert envelope(admin.get("/api/donations/2147483647"), 404)["code"] == "not_found"


def test_bug_01_a_non_numeric_id_is_still_a_422(admin):
    envelope(admin.get("/api/donations/abc"), 422)


# --- BUG-02: huge ids in query strings are a 422 ---------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/api/forecasts/series?pantry_id=99999999999&category=produce",
        "/api/forecasts?pantry_id=99999999999",
        "/api/forecasts?run_id=99999999999",
        "/api/forecasts/series?pantry_id=0&category=produce",
    ],
)
def test_bug_02_out_of_range_query_ids_are_a_422(admin, url):
    envelope(admin.get(url), 422)


# --- BUG-03 / BUG-04 / BUG-05: dates and months are limited to 2020 to 2100 -----------------


@pytest.mark.parametrize("week", ["9999-12-31", "0001-01-01", "2019-12-30", "2101-01-04"])
def test_bug_03_allocation_weeks_outside_2020_2100_are_a_422_with_a_clear_message(admin, week):
    error = envelope(admin.get(f"/api/allocations?week_start={week}"), 422)
    assert "between 2020 and 2100" in str(error["details"])


def test_bug_03_forecast_week_filter_has_the_same_limit(admin):
    envelope(admin.get("/api/forecasts?week_start=9999-12-27"), 422)


@pytest.mark.parametrize(
    "query",
    [
        "start=9999-01-01&end=9999-12-31",
        "start=0001-01-01&end=0001-02-01",
        "start=2026-01-01&end=9999-12-31",
        "end=9999-12-31",
        "start=1999-01-01",
    ],
)
def test_bug_04_dashboard_dates_outside_2020_2100_are_a_422(admin, query):
    error = envelope(admin.get(f"/api/dashboard/metrics?{query}"), 422)
    assert "between 2020 and 2100" in str(error["details"])


@pytest.mark.parametrize("month", ["0000-01", "2019-12", "2101-01", "9999-12"])
def test_bug_05_months_outside_2020_2100_are_a_422(admin, month):
    for method, path in [("GET", ""), ("POST", "/draft"), ("POST", "/approve")]:
        response = admin.request(
            method,
            f"/api/dashboard/summaries/{month}{path}",
            json={"text": "x"} if path == "/approve" else None,
        )
        error = envelope(response, 422)
        assert "2020-01 and 2100-12" in str(error["details"])


def test_expiry_dates_are_limited_to_2020_2100_too(admin, people):
    donation_id = _upload(admin)
    for expiry, ok in [("9999-12-31", False), ("2019-01-01", False)]:
        item = {"name": "x", "category": "produce", "quantity": 1, "unit": "case", "estimated_weight_lbs": 10,
                "expiry_date": expiry, "storage_type": "refrigerated", "source_index": None}  # fmt: skip
        response = admin.post(
            f"/api/donations/{donation_id}/confirm", json={"donor_name": "D", "items": [item]}
        )
        error = envelope(response, 422)
        assert "items.0.expiry_date" in str(error["details"])
        assert ok is False


def _upload(client) -> int:
    from tests.fakes import extraction

    client.app.state.llm.script(extraction())
    response = client.post(
        "/api/donations", files={"file": ("m.txt", b"10 cases of chicken", "text/plain")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- BUG-06: control characters are a 422, never a 500 -----------------------------------------


def test_bug_06_a_nul_in_a_shortage_note_is_a_422(client, people):
    login(client, people.manager)
    response = client.post(
        "/api/pantry/shortage-reports",
        json={"category": "dairy", "severity": 1, "note": "a\u0000b"},
    )
    assert "control characters" in str(envelope(response, 422)["details"])


def test_bug_06_a_nul_in_the_summary_text_is_a_422(admin):
    response = admin.post("/api/dashboard/summaries/2026-09/approve", json={"text": "a\u0000b"})
    assert "control characters" in str(envelope(response, 422)["details"])


def test_bug_06_a_nul_in_the_login_email_is_a_422_even_when_logged_out(client):
    response = client.post("/api/auth/login", json={"email": "a\u0000b@c.de", "password": "x"})
    envelope(response, 422)


def test_bug_06_a_nul_in_an_allocation_edit_note_is_a_422(admin, allocation_world):
    from app.ai.llm_provider import LLMTimeout

    admin.app.state.llm.script(LLMTimeout("slow"))
    assert admin.post("/api/forecasts/run").status_code in (201, 422)
    run = admin.post("/api/allocations/run")
    assert run.status_code == 201, run.text
    first = admin.get("/api/allocations").json()["rows"][0]["id"]
    response = admin.post(f"/api/allocations/{first}/edit", json={"lbs": 5, "note": "a\u0000b"})
    envelope(response, 422)


def test_notes_may_contain_new_lines_and_tabs(client, people):
    login(client, people.manager)
    response = client.post(
        "/api/pantry/shortage-reports",
        json={"category": "dairy", "severity": 1, "note": "line one\nline\ttwo"},
    )
    assert response.status_code == 201


def test_names_and_units_may_not_contain_new_lines(admin):
    donation_id = _upload(admin)
    item = {"name": "a\nb", "category": "produce", "quantity": 1, "unit": "case", "estimated_weight_lbs": 10,
            "expiry_date": None, "storage_type": "refrigerated", "source_index": None}  # fmt: skip
    envelope(
        admin.post(
            f"/api/donations/{donation_id}/confirm", json={"donor_name": "D", "items": [item]}
        ),
        422,
    )


def test_a_donor_name_with_a_control_character_is_a_422(admin):
    donation_id = _upload(admin)
    item = {"name": "x", "category": "produce", "quantity": 1, "unit": "case", "estimated_weight_lbs": 10,
            "expiry_date": None, "storage_type": "refrigerated", "source_index": None}  # fmt: skip
    envelope(
        admin.post(
            f"/api/donations/{donation_id}/confirm", json={"donor_name": "D\u0000", "items": [item]}
        ),
        422,
    )


def test_text_the_model_wrote_is_cleaned_of_control_characters(admin):
    from tests.fakes import extraction, item

    admin.app.state.llm.script(
        extraction(items=[item(name="Chicken\u0000 thighs\u0007")], donor="Mar\u0000ket")
    )
    response = admin.post("/api/donations", files={"file": ("m.txt", b"10 cases", "text/plain")})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["items"][0]["name"] == "Chicken thighs"
    assert body["suggested_donor_name"] == "Market"


def test_a_filename_with_a_control_character_is_cleaned(admin):
    from tests.fakes import extraction

    admin.app.state.llm.script(extraction())
    response = admin.post(
        "/api/donations", files={"file": ("a\u0000b\u0007.txt", b"10 cases", "text/plain")}
    )
    assert response.status_code == 201, response.text
    assert "\u0000" not in response.json()["original_filename"]


# --- BUG-09: the donation list pages through everything --------------------------------------


def _make_donations(client, n):
    from tests.fakes import extraction

    ids = []
    for i in range(n):
        client.app.state.llm.script(extraction())
        response = client.post(
            "/api/donations", files={"file": (f"m{i}.txt", b"10 cases", "text/plain")}
        )
        ids.append(response.json()["id"])
    return ids


@pytest.mark.usefixtures("clean_donations")
def test_bug_09_the_list_reports_the_total_and_pages_with_offset(admin):
    ids = _make_donations(admin, 5)
    first = admin.get("/api/donations?limit=2&offset=0")
    assert first.headers["x-total-count"] == "5"
    assert [d["id"] for d in first.json()] == ids[::-1][:2]
    second = admin.get("/api/donations?limit=2&offset=2")
    assert [d["id"] for d in second.json()] == ids[::-1][2:4]
    last = admin.get("/api/donations?limit=2&offset=4")
    assert [d["id"] for d in last.json()] == ids[::-1][4:]
    assert admin.get("/api/donations?limit=2&offset=100").json() == []


@pytest.mark.usefixtures("clean_donations")
def test_bug_09_the_total_respects_the_status_filter(admin):
    ids = _make_donations(admin, 3)
    admin.post(f"/api/donations/{ids[0]}/reject")
    assert admin.get("/api/donations?status=rejected").headers["x-total-count"] == "1"
    assert admin.get("/api/donations?status=pending_review").headers["x-total-count"] == "2"


@pytest.mark.parametrize("query", ["offset=-1", "offset=99999999999", "limit=0", "limit=201"])
def test_bug_09_paging_inputs_are_validated(admin, query):
    envelope(admin.get(f"/api/donations?{query}"), 422)
