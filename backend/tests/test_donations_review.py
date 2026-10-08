"""List, detail, confirm and reject: the human-in-the-loop half of intake."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import login, row_count
from tests.fakes import confidence, extraction, item

pytestmark = pytest.mark.usefixtures("clean_donations", "people")

TODAY = datetime.now(UTC).date()
SOON = (TODAY + timedelta(days=5)).isoformat()

THREE_ITEMS = [
    item(name="Chicken thighs", category="protein", quantity=10, unit="case",
         estimated_weight_lbs=400, expiry_date=SOON, storage_type="refrigerated"),
    item(name="Romaine lettuce", category="produce", quantity=10, unit="case",
         estimated_weight_lbs=300, expiry_date=SOON, storage_type="refrigerated",
         confidence=confidence(expiry_date=0.6)),
    item(name="Frozen meals", category="frozen", quantity=4, unit="case",
         estimated_weight_lbs=120, expiry_date=None, storage_type="frozen"),
]  # fmt: skip


def upload(client, llm, items=None, donor="Greenfield Market"):
    llm.script(extraction(THREE_ITEMS if items is None else items, donor=donor))
    response = client.post(
        "/api/donations", files={"file": ("m.txt", b"10 cases chicken", "text/plain")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def payload(detail, donor_name="Greenfield Market", donor_id=None, edit=None, drop=(), add=()):
    """What the review screen would send: the items as extracted, optionally edited."""
    items = []
    for index, it in enumerate(detail["items"]):
        if index in drop:
            continue
        row = {k: it[k] for k in ("name", "category", "quantity", "unit", "estimated_weight_lbs",
                                  "expiry_date", "storage_type")}  # fmt: skip
        row["source_index"] = index
        row.update((edit or {}).get(index, {}))
        items.append(row)
    items.extend(add)
    body = {"items": items}
    if donor_id is not None:
        body["donor_id"] = donor_id
    elif donor_name is not None:
        body["donor_name"] = donor_name
    return body


def new_row(**overrides):
    base = {"name": "Canned corn", "category": "canned", "quantity": 5, "unit": "case",
            "estimated_weight_lbs": 140, "expiry_date": None, "storage_type": "ambient"}  # fmt: skip
    return {**base, **overrides}


def confirm(client, detail, **kwargs):
    return client.post(f"/api/donations/{detail['id']}/confirm", json=payload(detail, **kwargs))


def reject(client, donation_id):
    return client.post(f"/api/donations/{donation_id}/reject")


def counts(engine):
    return {
        t: row_count(engine, t) for t in ("donations", "donation_items", "inventory_lots", "donors")
    }


def query(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


@pytest.fixture
def coordinator(client, people):
    login(client, people.coordinator)
    return client


# --- list ------------------------------------------------------------------------------------------


def test_the_list_is_empty_when_there_are_no_donations(coordinator):
    response = coordinator.get("/api/donations")
    assert response.status_code == 200 and response.json() == []


def test_the_list_shows_newest_first_with_counts_and_filters_by_status(coordinator, llm):
    first = upload(coordinator, llm, [item(estimated_weight_lbs=100)])
    second = upload(coordinator, llm)
    reject(coordinator, first["id"])
    everything = coordinator.get("/api/donations").json()
    assert [d["id"] for d in everything] == [second["id"], first["id"]]
    assert (everything[0]["item_count"], everything[0]["total_lbs"]) == (3, 820)
    assert everything[0]["status"] == "pending_review"
    pending = coordinator.get("/api/donations", params={"status": "pending_review"}).json()
    assert [d["id"] for d in pending] == [second["id"]]
    rejected = coordinator.get("/api/donations", params={"status": "rejected"}).json()
    assert [d["id"] for d in rejected] == [first["id"]]


def test_the_list_rejects_an_unknown_status_and_a_silly_limit(coordinator):
    assert coordinator.get("/api/donations", params={"status": "lost"}).status_code == 422
    assert coordinator.get("/api/donations", params={"limit": 0}).status_code == 422
    assert coordinator.get("/api/donations", params={"limit": 1000}).status_code == 422


# --- detail ----------------------------------------------------------------------------------------


def test_detail_returns_the_extracted_items_with_their_confidence(coordinator, llm):
    created = upload(coordinator, llm)
    detail = coordinator.get(f"/api/donations/{created['id']}").json()
    assert [i["name"] for i in detail["items"]] == [
        "Chicken thighs",
        "Romaine lettuce",
        "Frozen meals",
    ]
    assert detail["items"][1]["confidence"]["expiry_date"] == 0.6
    assert (
        detail["items"][2]["storage_type"] == "frozen"
        and detail["items"][2]["category"] == "frozen"
    )
    assert detail["suggested_donor_name"] == "Greenfield Market"


def test_unknown_and_malformed_ids(coordinator):
    assert coordinator.get("/api/donations/424242").status_code == 404
    assert coordinator.get("/api/donations/abc").status_code == 422


@pytest.mark.parametrize("path", ["/api/donations", "/api/donations/1", "/api/donors"])
def test_logged_out_users_get_401(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/api/donations", "/api/donations/1", "/api/donors"])
def test_pantry_managers_get_403(client, people, path):
    login(client, people.manager)
    assert client.get(path).status_code == 403


# --- confirm ---------------------------------------------------------------------------------------


def test_confirm_creates_items_and_one_lot_per_item(coordinator, llm, migrated_engine):
    detail = upload(coordinator, llm)
    response = confirm(coordinator, detail)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "confirmed" and body["donor_name"] == "Greenfield Market"
    assert [i["name"] for i in body["items"]] == [
        "Chicken thighs",
        "Romaine lettuce",
        "Frozen meals",
    ]
    assert counts(migrated_engine) == {
        "donations": 1,
        "donation_items": 3,
        "inventory_lots": 3,
        "donors": 1,
    }

    lots = query(
        migrated_engine,
        "SELECT i.name, c.name, l.storage_type, l.received_lbs, l.remaining_lbs, l.expired_lbs, "
        "l.status, l.received_date, l.expiry_date FROM inventory_lots l "
        "JOIN donation_items i ON i.id = l.donation_item_id "
        "JOIN categories c ON c.id = l.category_id ORDER BY l.id",
    )
    names = [(r[0], r[1], r[2]) for r in lots]
    assert names == [("Chicken thighs", "protein", "refrigerated"),
                     ("Romaine lettuce", "produce", "refrigerated"),
                     ("Frozen meals", "frozen", "frozen")]  # fmt: skip
    assert [float(r[3]) for r in lots] == [400, 300, 120]
    assert all(
        float(r[4]) == float(r[3]) and float(r[5]) == 0 and r[6] == "available" for r in lots
    )
    assert all(r[7] == TODAY for r in lots)
    assert [r[8] for r in lots] == [date.fromisoformat(SOON), date.fromisoformat(SOON), None]


def test_frozen_chicken_is_protein_stored_frozen_in_the_inventory(
    coordinator, llm, migrated_engine
):
    chicken = item(name="Frozen chicken", category="protein", storage_type="frozen")
    detail = upload(coordinator, llm, [chicken])
    assert confirm(coordinator, detail).status_code == 200
    ((category, storage),) = query(
        migrated_engine,
        "SELECT c.name, l.storage_type FROM inventory_lots l JOIN categories c ON c.id = l.category_id",
    )
    assert (category, storage) == ("protein", "frozen")


def test_confirm_records_who_reviewed_and_when(coordinator, llm, migrated_engine, people):
    detail = upload(coordinator, llm)
    confirm(coordinator, detail)
    ((email, reviewed_at),) = query(
        migrated_engine,
        "SELECT u.email, d.reviewed_at FROM donations d JOIN users u ON u.id = d.reviewed_by",
    )
    assert email == people.coordinator and reviewed_at is not None


def test_untouched_rows_keep_the_models_confidence_and_are_not_flagged_edited(
    coordinator, llm, migrated_engine
):
    detail = upload(coordinator, llm)
    confirm(coordinator, detail)
    rows = query(migrated_engine, "SELECT name, edited, confidence FROM donation_items ORDER BY id")
    assert [r[1] for r in rows] == [False, False, False]
    assert rows[1][2]["expiry_date"] == 0.6 and rows[0][2]["name"] == 0.95


def test_edited_added_and_removed_rows_are_handled(coordinator, llm, migrated_engine):
    detail = upload(coordinator, llm)
    response = confirm(
        coordinator,
        detail,
        edit={0: {"quantity": 12, "estimated_weight_lbs": 480}},
        drop=(2,),
        add=(new_row(),),
    )
    assert response.status_code == 200, response.text
    rows = query(
        migrated_engine,
        "SELECT i.name, i.edited, i.estimated_weight_lbs, l.received_lbs FROM donation_items i "
        "JOIN inventory_lots l ON l.donation_item_id = i.id ORDER BY i.id",
    )
    assert [(r[0], r[1]) for r in rows] == [("Chicken thighs", True), ("Romaine lettuce", False),
                                            ("Canned corn", True)]  # fmt: skip
    assert float(rows[0][2]) == 480 and float(rows[0][3]) == 480  # the lot uses the edited weight
    assert counts(migrated_engine)["inventory_lots"] == 3  # one removed, one added
    added_confidence = query(
        migrated_engine, "SELECT confidence FROM donation_items WHERE name = 'Canned corn'"
    )
    assert added_confidence[0][0] == {}


def test_an_existing_donor_can_be_chosen_by_id(coordinator, llm, migrated_engine):
    first = upload(coordinator, llm)
    confirm(coordinator, first)
    (donor_id,) = query(migrated_engine, "SELECT id FROM donors")[0]
    second = upload(coordinator, llm)
    response = confirm(coordinator, second, donor_id=donor_id, donor_name=None)
    assert response.status_code == 200 and response.json()["donor_id"] == donor_id
    assert counts(migrated_engine)["donors"] == 1


def test_a_new_donor_name_reuses_an_existing_donor_ignoring_case(coordinator, llm, migrated_engine):
    confirm(coordinator, upload(coordinator, llm))
    confirm(coordinator, upload(coordinator, llm), donor_name="  GREENFIELD market ")
    assert counts(migrated_engine)["donors"] == 1


def test_a_new_donor_is_created_with_type_other(coordinator, llm, migrated_engine):
    confirm(coordinator, upload(coordinator, llm), donor_name="Brand New Bakery")
    assert query(migrated_engine, "SELECT name, donor_type FROM donors") == [
        ("Brand New Bakery", "other")
    ]


def test_an_unknown_donor_id_is_a_validation_error_and_creates_nothing(
    coordinator, llm, migrated_engine
):
    detail = upload(coordinator, llm)
    response = confirm(coordinator, detail, donor_id=424242, donor_name=None)
    assert response.status_code == 422
    assert "donor_id" in [d["field"] for d in response.json()["error"]["details"]]
    assert counts(migrated_engine)["inventory_lots"] == 0


def test_the_donation_list_and_detail_reflect_a_confirmed_donation(coordinator, llm):
    detail = upload(coordinator, llm)
    confirm(coordinator, detail, edit={1: {"quantity": 11}})
    summary = coordinator.get("/api/donations", params={"status": "confirmed"}).json()[0]
    assert (summary["item_count"], summary["total_lbs"], summary["donor_name"]) == (
        3,
        820,
        "Greenfield Market",
    )
    again = coordinator.get(f"/api/donations/{detail['id']}").json()
    assert again["items"][1]["quantity"] == 11 and again["items"][1]["edited"] is True


BAD_PAYLOADS = {
    "no items": lambda d: {**payload(d), "items": []},
    "too many items": lambda d: {**payload(d), "items": payload(d)["items"] * 40},
    "zero quantity": lambda d: payload(d, edit={0: {"quantity": 0}}),
    "negative weight": lambda d: payload(d, edit={0: {"estimated_weight_lbs": -5}}),
    "unknown category": lambda d: payload(d, edit={0: {"category": "candy"}}),
    "unknown storage": lambda d: payload(d, edit={0: {"storage_type": "warm"}}),
    "blank name": lambda d: payload(d, edit={0: {"name": "  "}}),
    "bad date": lambda d: payload(d, edit={0: {"expiry_date": "soon"}}),
    "both donor fields": lambda d: {**payload(d), "donor_id": 1, "donor_name": "X"},
    "neither donor field": lambda d: {"items": payload(d)["items"]},
    "source index out of range": lambda d: payload(d, edit={0: {"source_index": 99}}),
}


@pytest.mark.parametrize("make", BAD_PAYLOADS.values(), ids=BAD_PAYLOADS.keys())
def test_invalid_confirmations_are_rejected_and_create_nothing(
    coordinator, llm, migrated_engine, make
):
    detail = upload(coordinator, llm)
    response = coordinator.post(f"/api/donations/{detail['id']}/confirm", json=make(detail))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert counts(migrated_engine) == {
        "donations": 1,
        "donation_items": 0,
        "inventory_lots": 0,
        "donors": 0,
    }
    assert coordinator.get(f"/api/donations/{detail['id']}").json()["status"] == "pending_review"


def test_an_item_that_has_already_expired_is_blocked_and_the_field_is_named(
    coordinator, llm, migrated_engine
):
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    detail = upload(coordinator, llm)
    response = confirm(coordinator, detail, edit={1: {"expiry_date": yesterday}})
    assert response.status_code == 422
    (problem,) = response.json()["error"]["details"]
    assert problem["field"] == "items.1.expiry_date" and "expired" in problem["message"]
    assert counts(migrated_engine)["inventory_lots"] == 0


def test_an_item_that_expires_today_is_allowed(coordinator, llm):
    detail = upload(coordinator, llm)
    assert (
        confirm(coordinator, detail, edit={0: {"expiry_date": TODAY.isoformat()}}).status_code
        == 200
    )


def test_perishables_without_an_expiry_date_only_warn_in_the_ui_not_the_api(coordinator, llm):
    detail = upload(coordinator, llm, [item(category="produce", expiry_date=None)])
    assert confirm(coordinator, detail).status_code == 200


def test_confirming_twice_is_a_409_and_does_not_duplicate_lots(coordinator, llm, migrated_engine):
    detail = upload(coordinator, llm)
    assert confirm(coordinator, detail).status_code == 200
    again = confirm(coordinator, detail)
    assert again.status_code == 409 and again.json()["error"]["code"] == "donation_not_pending"
    assert counts(migrated_engine)["inventory_lots"] == 3


def test_confirm_unknown_donation_is_404_and_roles_are_enforced(client, people, llm):
    login(client, people.coordinator)
    assert client.post("/api/donations/424242/confirm", json={}).status_code in (404, 422)
    detail = upload(client, llm)
    client.post("/api/auth/logout")
    assert (
        client.post(f"/api/donations/{detail['id']}/confirm", json=payload(detail)).status_code
        == 401
    )
    login(client, people.manager)
    assert (
        client.post(f"/api/donations/{detail['id']}/confirm", json=payload(detail)).status_code
        == 403
    )
    login(client, people.admin)
    assert (
        client.post(f"/api/donations/{detail['id']}/confirm", json=payload(detail)).status_code
        == 200
    )


# --- reject ----------------------------------------------------------------------------------------


def test_reject_saves_no_items_or_lots_but_keeps_the_audit_record(
    coordinator, llm, storage, migrated_engine
):
    detail = upload(coordinator, llm)
    response = reject(coordinator, detail["id"])
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert counts(migrated_engine) == {
        "donations": 1,
        "donation_items": 0,
        "inventory_lots": 0,
        "donors": 0,
    }
    ((status, reviewer, when, raw),) = query(
        migrated_engine, "SELECT status, reviewed_by, reviewed_at, raw_llm_output FROM donations"
    )
    assert status == "rejected" and reviewer is not None and when is not None and raw is not None
    assert len([p for p in storage.root.rglob("*") if p.is_file()]) == 1
    shown = coordinator.get(f"/api/donations/{detail['id']}").json()
    assert shown["status"] == "rejected" and len(shown["items"]) == 3  # still visible, read-only


def test_a_rejected_donation_cannot_be_confirmed_or_rejected_again(
    coordinator, llm, migrated_engine
):
    detail = upload(coordinator, llm)
    reject(coordinator, detail["id"])
    assert confirm(coordinator, detail).status_code == 409
    assert reject(coordinator, detail["id"]).status_code == 409
    assert counts(migrated_engine)["inventory_lots"] == 0


def test_a_confirmed_donation_cannot_be_rejected(coordinator, llm, migrated_engine):
    detail = upload(coordinator, llm)
    confirm(coordinator, detail)
    response = reject(coordinator, detail["id"])
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "donation_not_pending"
    )
    assert counts(migrated_engine)["inventory_lots"] == 3


def test_reject_unknown_donation_and_roles(client, people, llm):
    login(client, people.coordinator)
    assert reject(client, 424242).status_code == 404
    detail = upload(client, llm)
    login(client, people.manager)
    assert reject(client, detail["id"]).status_code == 403
    client.post("/api/auth/logout")
    assert reject(client, detail["id"]).status_code == 401


# --- donors ----------------------------------------------------------------------------------------


def test_donors_are_listed_alphabetically_ignoring_case(coordinator, llm):
    assert coordinator.get("/api/donors").json() == []
    confirm(coordinator, upload(coordinator, llm), donor_name="zebra Farm")
    confirm(coordinator, upload(coordinator, llm), donor_name="Apple Orchard")
    confirm(coordinator, upload(coordinator, llm), donor_name="mango Market")
    names = [d["name"] for d in coordinator.get("/api/donors").json()]
    assert names == ["Apple Orchard", "mango Market", "zebra Farm"]
