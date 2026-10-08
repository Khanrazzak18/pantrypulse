"""Allocation runs and decisions: what the optimizer may propose, and what approving does."""

import time
from collections import defaultdict
from datetime import date

import pytest
from sqlalchemy import text

from app.ai.llm_provider import LLMTimeout
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people", "allocation_world")


@pytest.fixture(autouse=True)
def reasons_down(llm):
    """By default the reason call fails, so runs fall back to templates. Tests override this."""
    llm.script(LLMTimeout("slow"))


@pytest.fixture
def coordinator(client, people):
    login(client, people.coordinator)
    return client


def run(client):
    return client.post("/api/allocations/run")


def rows_of(client, **params):
    response = client.get("/api/allocations", params=params)
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def query(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def lot_remaining(engine, lot_id):
    return float(
        query(engine, "SELECT remaining_lbs FROM inventory_lots WHERE id=:i", i=lot_id)[0][0]
    )


def lot_with_two_rows(rows):
    by_lot = defaultdict(list)
    for r in rows:
        by_lot[r["lot"]["id"]].append(r)
    return next(v for v in by_lot.values() if len(v) >= 2)


def row_for(rows, lot_id=None, pantry_id=None):
    return next(
        r
        for r in rows
        if (lot_id is None or r["lot"]["id"] == lot_id)
        and (pantry_id is None or r["pantry"]["id"] == pantry_id)
    )


# --- permissions ------------------------------------------------------------------------------


def test_logged_out_requests_get_401(client):
    assert run(client).status_code == 401
    assert client.get("/api/allocations").status_code == 401


def test_pantry_managers_cannot_run_or_decide(client, people, coordinator, engine):
    run(coordinator)
    allocation_id = rows_of(coordinator)[0]["id"]
    client.cookies.clear()
    login(client, people.manager)
    assert run(client).status_code == 403
    assert client.get("/api/allocations").status_code == 403
    for path, body in [
        (f"/api/allocations/{allocation_id}/approve", None),
        (f"/api/allocations/{allocation_id}/reject", None),
        (f"/api/allocations/{allocation_id}/edit", {"lbs": 5}),
        ("/api/allocations/bulk-approve", {"ids": [allocation_id]}),
    ]:
        assert client.post(path, json=body).status_code == 403, path
    status = query(engine, "SELECT status FROM allocations WHERE id=:i", i=allocation_id)[0][0]
    assert status == "proposed"


def test_admin_can_run(client, people):
    login(client, people.admin)
    assert run(client).status_code == 201


# --- what a run proposes ----------------------------------------------------------------------


def test_run_never_exceeds_supply_capacity_or_p90(coordinator, allocation_world, engine):
    response = run(coordinator)
    assert response.status_code == 201
    out = response.json()
    assert out["week_start"] == "2026-10-05"
    assert out["delivery_date"] == "2026-10-06"  # today, inside the forecast week
    rows = rows_of(coordinator)
    assert rows

    per_lot = defaultdict(float)
    cold = defaultdict(float)
    per_cell = defaultdict(float)
    for r in rows:
        assert r["status"] == "proposed"
        assert r["recommended_lbs"] > 0
        per_lot[r["lot"]["id"]] += r["recommended_lbs"]
        if r["lot"]["storage_type"] != "ambient":
            cold[r["pantry"]["id"]] += r["recommended_lbs"]
        per_cell[r["pantry"]["id"], r["lot"]["category"]] += r["recommended_lbs"]
    for lot_id, lbs in per_lot.items():
        assert lbs <= lot_remaining(engine, lot_id) + 0.01
    assert cold[923] <= 150 + 0.01  # pantry 923 has a small cold room
    p90 = {
        (p, {1: "produce", 2: "dairy", 6: "canned"}[c]): v[1]
        for (p, c), v in allocation_world.wants.items()
    }
    for key, lbs in per_cell.items():
        assert lbs <= p90[key] + 0.01


def test_soonest_expiring_lot_ships_first(coordinator, allocation_world):
    run(coordinator)
    rows = rows_of(coordinator)
    shipped = defaultdict(float)
    for r in rows:
        shipped[r["lot"]["id"]] += r["recommended_lbs"]
    a, b = allocation_world.lots["A"], allocation_world.lots["B"]
    # produce demand (to P90) is 1,170 lb and the two produce lots hold 1,300: the lot that
    # expires in 3 days goes out in full while the 14-day lot keeps the leftover
    assert shipped[a] == pytest.approx(500, abs=0.05)
    assert shipped[b] < 800


def test_expired_lot_is_excluded_and_reported(coordinator, allocation_world):
    out = run(coordinator).json()
    assert out["lots_excluded"] == 1
    assert all(r["lot"]["id"] != allocation_world.lots["E"] for r in rows_of(coordinator))


def test_no_forecast_is_a_clear_422(coordinator, engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM forecasts"))
        conn.execute(text("DELETE FROM forecast_runs"))
    response = run(coordinator)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_forecast"


def test_no_inventory_is_a_clear_422(coordinator, engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE inventory_lots SET remaining_lbs=0, status='depleted'"))
    response = run(coordinator)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_inventory"


def test_a_run_is_fast(coordinator):
    started = time.monotonic()
    assert run(coordinator).status_code == 201
    assert time.monotonic() - started < 20


# --- approve, edit, reject --------------------------------------------------------------------


def test_approve_sets_final_lbs_delivery_and_takes_stock(coordinator, engine):
    run(coordinator)
    row = rows_of(coordinator)[0]
    before = lot_remaining(engine, row["lot"]["id"])
    response = coordinator.post(f"/api/allocations/{row['id']}/approve")
    assert response.status_code == 200
    out = response.json()
    assert out["status"] == "approved"
    assert out["final_lbs"] == row["recommended_lbs"]
    assert out["delivery_date"] == "2026-10-06"
    assert lot_remaining(engine, row["lot"]["id"]) == pytest.approx(before - row["recommended_lbs"])
    log = query(
        engine,
        "SELECT field, old_value, new_value FROM allocation_edits WHERE allocation_id=:i",
        i=row["id"],
    )
    assert ("status", "proposed", "approved") in log


def test_approving_twice_is_a_conflict(coordinator):
    run(coordinator)
    row_id = rows_of(coordinator)[0]["id"]
    assert coordinator.post(f"/api/allocations/{row_id}/approve").status_code == 200
    again = coordinator.post(f"/api/allocations/{row_id}/approve")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "allocation_decided"


def test_edit_saves_new_amount_and_is_logged(coordinator, engine, people):
    run(coordinator)
    row = rows_of(coordinator)[0]
    new_lbs = round(row["recommended_lbs"] / 2, 2)
    response = coordinator.post(
        f"/api/allocations/{row['id']}/edit", json={"lbs": new_lbs, "note": "Truck is small"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "edited"
    assert response.json()["final_lbs"] == new_lbs
    log = {
        (field, old, new)
        for field, old, new in query(
            engine,
            "SELECT field, old_value, new_value FROM allocation_edits WHERE allocation_id=:i",
            i=row["id"],
        )
    }
    changes = {(f, o, n) for f, o, n in log if f == "final_lbs"}
    assert len(changes) == 1
    _, old, new = changes.pop()
    assert float(old) == row["recommended_lbs"] and float(new) == new_lbs
    assert ("note", None, "Truck is small") in log
    assert ("status", "proposed", "edited") in log
    who = query(
        engine, "SELECT DISTINCT u.email FROM allocation_edits e JOIN users u ON u.id=e.user_id"
    )
    assert who == [(people.coordinator,)]


@pytest.mark.parametrize("lbs", [0, -5])
def test_edit_must_be_positive(coordinator, lbs):
    run(coordinator)
    row_id = rows_of(coordinator)[0]["id"]
    response = coordinator.post(f"/api/allocations/{row_id}/edit", json={"lbs": lbs})
    assert response.status_code == 422


def test_edit_cannot_exceed_what_the_lot_has(coordinator, engine):
    run(coordinator)
    row = rows_of(coordinator)[0]
    too_much = lot_remaining(engine, row["lot"]["id"]) + 1
    response = coordinator.post(f"/api/allocations/{row['id']}/edit", json={"lbs": too_much})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert rows_of(coordinator)[0]["status"] == "proposed"


def test_edit_note_is_limited_to_500_chars(coordinator):
    run(coordinator)
    row_id = rows_of(coordinator)[0]["id"]
    response = coordinator.post(
        f"/api/allocations/{row_id}/edit", json={"lbs": 1, "note": "x" * 501}
    )
    assert response.status_code == 422


def test_reject_leaves_the_lot_alone_and_it_is_proposed_again(coordinator, engine):
    run(coordinator)
    row = rows_of(coordinator)[0]
    before = lot_remaining(engine, row["lot"]["id"])
    response = coordinator.post(f"/api/allocations/{row['id']}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["final_lbs"] is None
    assert lot_remaining(engine, row["lot"]["id"]) == before
    assert ("status", "proposed", "rejected") in query(
        engine,
        "SELECT field, old_value, new_value FROM allocation_edits WHERE allocation_id=:i",
        i=row["id"],
    )
    run(coordinator)
    proposed = [r for r in rows_of(coordinator) if r["status"] == "proposed"]
    assert any(
        r["lot"]["id"] == row["lot"]["id"] and r["pantry"]["id"] == row["pantry"]["id"]
        for r in proposed
    )


def test_second_approval_cannot_overallocate_a_lot(coordinator, engine):
    run(coordinator)
    rows = rows_of(coordinator)
    same_lot = lot_with_two_rows(rows)
    lot_id = same_lot[0]["lot"]["id"]
    first, second = same_lot[0], same_lot[1]
    with engine.begin() as conn:  # leave room for the first row only
        conn.execute(
            text("UPDATE inventory_lots SET remaining_lbs=:r WHERE id=:i"),
            {"r": first["recommended_lbs"], "i": lot_id},
        )
    assert coordinator.post(f"/api/allocations/{first['id']}/approve").status_code == 200
    response = coordinator.post(f"/api/allocations/{second['id']}/approve")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lot_short"
    assert lot_remaining(engine, lot_id) >= 0


def test_approving_a_lot_that_has_expired_is_refused(coordinator, engine):
    run(coordinator)
    row = row_for(rows_of(coordinator), lot_id=None)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE inventory_lots SET expiry_date='2026-10-01' WHERE id=:i"),
            {"i": row["lot"]["id"]},
        )
    response = coordinator.post(f"/api/allocations/{row['id']}/approve")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lot_expired"


# --- bulk approve -----------------------------------------------------------------------------


def test_bulk_approve_approves_every_listed_row(coordinator):
    run(coordinator)
    ids = [r["id"] for r in rows_of(coordinator)][:5]
    response = coordinator.post("/api/allocations/bulk-approve", json={"ids": ids})
    assert response.status_code == 200
    assert response.json()["approved"] == len(ids)
    decided = {r["id"]: r["status"] for r in rows_of(coordinator)}
    assert all(decided[i] == "approved" for i in ids)


def test_bulk_approve_is_all_or_nothing(coordinator, engine):
    run(coordinator)
    rows = rows_of(coordinator)
    ids = [r["id"] for r in rows][:4]
    coordinator.post(f"/api/allocations/{ids[-1]}/reject")  # one of them is already decided
    response = coordinator.post("/api/allocations/bulk-approve", json={"ids": ids})
    assert response.status_code == 409
    statuses = {r["id"]: r["status"] for r in rows_of(coordinator)}
    assert all(statuses[i] == "proposed" for i in ids[:-1])


def test_bulk_approve_checks_the_lots_in_total(coordinator, engine):
    run(coordinator)
    rows = rows_of(coordinator)
    same_lot = lot_with_two_rows(rows)[:2]
    lot_id = same_lot[0]["lot"]["id"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE inventory_lots SET remaining_lbs=:r WHERE id=:i"),
            {"r": same_lot[0]["recommended_lbs"], "i": lot_id},
        )
    response = coordinator.post(
        "/api/allocations/bulk-approve", json={"ids": [r["id"] for r in same_lot]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lot_short"
    assert all(
        r["status"] == "proposed"
        for r in rows_of(coordinator)
        if r["id"] in {s["id"] for s in same_lot}
    )


# --- re-running -------------------------------------------------------------------------------


def test_rerun_replaces_undecided_rows_and_keeps_decided_ones(coordinator, engine):
    run(coordinator)
    first = rows_of(coordinator)
    approved = first[0]
    coordinator.post(f"/api/allocations/{approved['id']}/approve")
    n_first = len(first)
    run(coordinator)
    after = rows_of(coordinator)
    assert any(r["id"] == approved["id"] and r["status"] == "approved" for r in after)
    ids_after = {r["id"] for r in after}
    assert not (ids_after & {r["id"] for r in first[1:]})  # the undecided rows are gone
    proposed = [r for r in after if r["status"] == "proposed"]
    assert 0 < len(proposed) <= n_first + 5


def test_rerun_nets_out_approved_pounds(coordinator, engine, allocation_world):
    run(coordinator)
    for r in rows_of(coordinator):
        if r["status"] == "proposed":
            coordinator.post(f"/api/allocations/{r['id']}/approve")
    run(coordinator)
    after = rows_of(coordinator)
    per_cell = defaultdict(float)
    cold = defaultdict(float)
    for r in after:
        lbs = r["final_lbs"] if r["final_lbs"] is not None else r["recommended_lbs"]
        if r["status"] == "rejected":
            continue
        per_cell[r["pantry"]["id"], r["lot"]["category"]] += lbs
        if r["lot"]["storage_type"] != "ambient":
            cold[r["pantry"]["id"]] += lbs
    p90 = {
        (p, {1: "produce", 2: "dairy", 6: "canned"}[c]): v[1]
        for (p, c), v in allocation_world.wants.items()
    }
    for key, lbs in per_cell.items():
        assert lbs <= p90[key] + 0.05  # approved plus newly proposed still stays within P90
    assert cold[923] <= 150 + 0.05
    for lot_id in allocation_world.lots.values():
        assert lot_remaining(engine, lot_id) >= 0


# --- reasons ----------------------------------------------------------------------------------


def test_every_row_has_a_reason_and_a_source_tag(coordinator, llm):
    llm.script(LLMTimeout("slow"))
    out = run(coordinator).json()
    rows = rows_of(coordinator)
    assert out["reasons_ai"] == 0
    assert out["reasons_template"] == len(rows)
    assert all(r["reason"] and r["reason_source"] == "template" for r in rows)


def test_a_failed_reason_call_does_not_fail_the_run(coordinator, llm):
    llm.script(LLMTimeout("slow"))
    assert run(coordinator).status_code == 201
    assert len(llm.calls) == 1  # no retry


def test_ai_reasons_are_used_when_they_pass_the_checks(coordinator, llm):
    def good(call):
        import json

        facts = json.loads(call["content"][0]["text"])
        return {
            "reasons": [
                {
                    "id": f["id"],
                    "reason": f"{f['pantry']}: forecast short {f['forecast_lbs']} lb "
                    f"{f['category']}, {f['miles']:g} miles away",
                }
                for f in facts
            ]
        }

    llm.script(good)
    out = run(coordinator).json()
    rows = rows_of(coordinator)
    assert out["reasons_ai"] > 0
    assert out["reasons_ai"] + out["reasons_template"] == len(rows)
    assert {r["reason_source"] for r in rows} <= {"ai", "template"}
    assert any(r["reason_source"] == "ai" for r in rows)
    assert llm.calls[0]["timeout_seconds"] == 10.0


def test_ai_reason_with_an_invented_number_keeps_the_template(coordinator, llm):
    def bad(call):
        import json

        facts = json.loads(call["content"][0]["text"])
        return {
            "reasons": [
                {"id": f["id"], "reason": f"{f['pantry']}: needs 99999 lb urgently"} for f in facts
            ]
        }

    llm.script(bad)
    out = run(coordinator).json()
    assert out["reasons_ai"] == 0


def test_write_more_reasons_fills_in_templates(coordinator, llm):
    llm.script(LLMTimeout("slow"))
    run_id = run(coordinator).json()["id"]

    def good(call):
        import json

        facts = json.loads(call["content"][0]["text"])
        return {
            "reasons": [
                {
                    "id": f["id"],
                    "reason": f"{f['pantry']}: forecast short {f['forecast_lbs']} lb "
                    f"{f['category']}, {f['miles']:g} miles away",
                }
                for f in facts
            ]
        }

    llm.script(good)
    response = coordinator.post(f"/api/allocations/runs/{run_id}/reasons")
    assert response.status_code == 200
    assert response.json()["reasons_ai"] > 0
    assert any(r["reason_source"] == "ai" for r in rows_of(coordinator))


# --- reading ----------------------------------------------------------------------------------


def test_latest_run_and_empty_list(coordinator):
    assert coordinator.get("/api/allocations/runs/latest").json() == {"run": None}
    assert coordinator.get("/api/allocations").json()["rows"] == []
    run(coordinator)
    latest = coordinator.get("/api/allocations/runs/latest").json()["run"]
    assert latest["week_start"] == "2026-10-05"
    assert latest["rows"] == len(rows_of(coordinator))


def test_rows_describe_the_pantry_and_the_lot(coordinator):
    run(coordinator)
    row = rows_of(coordinator)[0]
    assert {"id", "name", "county", "miles"} <= set(row["pantry"])
    assert {"id", "item_name", "category", "storage_type", "expiry_date", "remaining_lbs",
            "days_left"} <= set(row["lot"])  # fmt: skip
    assert row["lot"]["expiry_date"] is None or date.fromisoformat(row["lot"]["expiry_date"])


def test_list_can_filter_by_status(coordinator):
    run(coordinator)
    row_id = rows_of(coordinator)[0]["id"]
    coordinator.post(f"/api/allocations/{row_id}/reject")
    assert [r["id"] for r in rows_of(coordinator, status="rejected")] == [row_id]
    assert all(r["status"] == "proposed" for r in rows_of(coordinator, status="proposed"))
