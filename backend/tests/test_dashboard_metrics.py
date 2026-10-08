"""Impact dashboard numbers on a fixture small enough to check by hand.

Distributions (pantry, category, week -> lbs, households):
  W1 (Sep 7):  931 produce 100/50, 931 canned 200/50, 932 produce 40/20, 932 canned 60/20
  W2 (Sep 14): 931 produce 120/60, 931 canned 180/60, 932 produce 10/5
Households once per pantry-week: W1 50 + 20 = 70, W2 60 + 5 = 65, total 135 (summing every
category row would give 270). Lbs: W1 400, W2 310, total 710; produce 270, canned 440.
Shortage reports: 3 (W1 two, W2 one). There are 4 pantry-weeks (931 and 932, W1 and W2), and 3 of
them have a report: 75%.
Perishable (produce) lots: received 1000 + 500, expired 120 + 30 -> 10.0%; W1 12.0%, W2 6.0%.
The canned lot is not perishable and stays out of spoilage.
"""

import pytest

from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people", "impact_world")


@pytest.fixture
def admin(client, people):
    login(client, people.admin)
    return client


def metrics(client, **params):
    response = client.get("/api/dashboard/metrics", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_totals_over_the_whole_range(admin):
    t = metrics(admin, start="2026-09-07", end="2026-09-14")["totals"]
    assert t["lbs_distributed"] == pytest.approx(710)
    assert t["households_served"] == 135  # once per pantry-week, not once per category row
    assert t["shortage_reports"] == 3
    assert t["pantry_weeks"] == 4
    assert t["pantry_weeks_with_shortage"] == 3
    assert t["stockout_pct"] == pytest.approx(75.0)
    assert t["received_perishable_lbs"] == pytest.approx(1500)
    assert t["expired_perishable_lbs"] == pytest.approx(150)
    assert t["spoilage_pct"] == pytest.approx(10.0)


def test_weekly_series(admin):
    weekly = {
        w["week_start"]: w for w in metrics(admin, start="2026-09-07", end="2026-09-14")["weekly"]
    }
    assert weekly["2026-09-07"]["lbs_distributed"] == pytest.approx(400)
    assert weekly["2026-09-07"]["households_served"] == 70
    assert weekly["2026-09-07"]["shortage_reports"] == 2
    assert weekly["2026-09-07"]["spoilage_pct"] == pytest.approx(12.0)
    assert weekly["2026-09-14"]["lbs_distributed"] == pytest.approx(310)
    assert weekly["2026-09-14"]["households_served"] == 65
    assert weekly["2026-09-14"]["spoilage_pct"] == pytest.approx(6.0)


def test_by_category(admin):
    by = {
        c["category"]: c
        for c in metrics(admin, start="2026-09-07", end="2026-09-14")["by_category"]
    }
    assert set(by) >= {"produce", "canned"}
    assert by["produce"]["lbs_distributed"] == pytest.approx(270)
    assert by["canned"]["lbs_distributed"] == pytest.approx(440)
    assert by["produce"]["shortage_reports"] == 2 and by["canned"]["shortage_reports"] == 1
    assert by["produce"]["spoilage_pct"] == pytest.approx(10.0)
    assert by["canned"]["spoilage_pct"] is None  # not perishable
    assert by["dairy"]["lbs_distributed"] == 0


def test_date_range_filter(admin):
    out = metrics(admin, start="2026-09-14", end="2026-09-14")
    t = out["totals"]
    assert t["lbs_distributed"] == pytest.approx(310)
    assert t["households_served"] == 65
    assert t["shortage_reports"] == 1
    assert t["spoilage_pct"] == pytest.approx(6.0)
    assert [w["week_start"] for w in out["weekly"]] == ["2026-09-14"]


def test_dates_snap_to_mondays(admin):
    out = metrics(admin, start="2026-09-10", end="2026-09-16")  # Thursday to Wednesday
    assert out["range"]["start"] == "2026-09-07" and out["range"]["end"] == "2026-09-14"


def test_default_range_ends_at_the_last_week_with_data(admin):
    out = metrics(admin)
    assert out["range"]["data_start"] == "2026-09-07" and out["range"]["data_end"] == "2026-09-14"
    assert out["range"]["end"] == "2026-09-14"


def test_start_after_end_is_a_validation_error(admin):
    response = admin.get(
        "/api/dashboard/metrics", params={"start": "2026-09-14", "end": "2026-09-07"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_a_range_with_no_data_is_empty_not_an_error(admin):
    out = metrics(admin, start="2020-01-06", end="2020-02-03")
    assert out["totals"]["lbs_distributed"] == 0 and out["totals"]["spoilage_pct"] is None
    assert out["totals"]["stockout_pct"] is None


def test_only_admins_see_the_dashboard(client, people):
    assert client.get("/api/dashboard/metrics").status_code == 401
    for email in (people.coordinator, people.manager):
        client.cookies.clear()
        login(client, email)
        assert client.get("/api/dashboard/metrics").status_code == 403
