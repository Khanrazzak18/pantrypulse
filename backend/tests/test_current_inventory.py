"""The seeded 'current inventory': stock on hand at the start of the forecast week, so the
Allocations page has something to allocate (alongside lots confirmed through intake)."""

from collections import defaultdict
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.constants import CATEGORY_NAMES, PERISHABLE_CATEGORIES
from scripts.generate_synthetic_data import (
    DEFAULT_SEED,
    SUPPLY_RATIO,
    add_current_inventory,
    fingerprint,
    generate,
)
from scripts.seed import load, truncate_app_tables

PASSWORDS = {"coordinator": "pw-c-1", "admin": "pw-a-1", "pantry_manager": "pw-m-1"}
PINNED = "09181a39f193e7030bf34aa3be0fda5333c48579f489344fc6260d5ff8151b20"


@pytest.fixture(scope="module")
def data():
    return add_current_inventory(generate(DEFAULT_SEED))


def monday_after_history(data):
    return max(d["week_start"] for d in data.distributions) + timedelta(weeks=1)


# --- the history is untouched ---------------------------------------------------------------------


def test_adding_current_inventory_does_not_change_the_historical_tables(data):
    assert fingerprint(data) == PINNED  # fingerprint covers the history only
    assert data.current_lots and data.current_donations and data.current_donation_items


def test_a_plain_generate_has_no_current_inventory():
    assert generate(DEFAULT_SEED).current_lots == []


# --- what the seeded stock looks like ------------------------------------------------------------


def test_the_set_is_reproducible_from_its_seed():
    a = add_current_inventory(generate(DEFAULT_SEED))
    b = add_current_inventory(generate(DEFAULT_SEED))
    assert a.current_lots == b.current_lots
    other = add_current_inventory(generate(DEFAULT_SEED), seed=1)
    assert other.current_lots != a.current_lots


def test_there_are_about_two_dozen_lots_across_every_category(data):
    assert 15 <= len(data.current_lots) <= 40
    assert {lot["category_id"] for lot in data.current_lots} == set(range(1, 9))


def test_every_lot_is_available_and_untouched(data):
    for lot in data.current_lots:
        assert lot["status"] == "available"
        assert lot["remaining_lbs"] == lot["received_lbs"] > 0
        assert lot["expired_lbs"] == 0


def test_totals_per_category_are_sized_to_recent_demand_times_the_supply_ratio(data):
    recent = sorted({d["week_start"] for d in data.distributions})[-4:]
    weekly = defaultdict(float)
    for d in data.distributions:
        if d["week_start"] in recent:
            weekly[d["category_id"]] += d["lbs"] / 4
    totals = defaultdict(float)
    for lot in data.current_lots:
        totals[lot["category_id"]] += lot["received_lbs"]
    for c in range(1, 9):
        ratio = totals[c] / weekly[c]
        assert 0.85 * SUPPLY_RATIO[c - 1] <= ratio <= 1.15 * SUPPLY_RATIO[c - 1], CATEGORY_NAMES[
            c - 1
        ]


def test_lots_arrived_in_the_days_before_the_forecast_monday(data):
    monday = monday_after_history(data)
    for lot in data.current_lots:
        assert 1 <= (monday - lot["received_date"]).days <= 3


def test_fresh_food_has_a_week_or_more_left_and_shelf_stable_food_much_longer(data):
    monday = monday_after_history(data)
    for lot in data.current_lots:
        days_left = (lot["expiry_date"] - monday).days
        cat = CATEGORY_NAMES[lot["category_id"] - 1]
        if cat in PERISHABLE_CATEGORIES and lot["storage_type"] != "frozen":
            assert 6 <= days_left <= 13
        else:
            assert days_left >= 90


def test_storage_follows_the_same_rules_as_the_history(data):
    for lot in data.current_lots:
        cat = CATEGORY_NAMES[lot["category_id"] - 1]
        if cat == "dairy":
            assert lot["storage_type"] == "refrigerated"
        if cat == "frozen":
            assert lot["storage_type"] == "frozen"
        if cat in ("canned", "dry_goods", "beverages", "bakery"):
            assert lot["storage_type"] == "ambient"
        if cat in ("produce", "protein"):
            assert lot["storage_type"] in ("refrigerated", "frozen", "ambient")


def test_ids_continue_after_the_history_and_every_reference_resolves(data):
    old_donation = max(d["id"] for d in data.donations)
    old_item = max(i["id"] for i in data.donation_items)
    assert min(d["id"] for d in data.current_donations) > old_donation
    assert min(i["id"] for i in data.current_donation_items) > old_item
    donations = {d["id"] for d in data.current_donations}
    donors = {d["id"] for d in data.donors}
    items = {i["id"]: i for i in data.current_donation_items}
    assert all(d["donor_id"] in donors for d in data.current_donations)
    assert all(i["donation_id"] in donations for i in data.current_donation_items)
    for lot in data.current_lots:
        item = items[lot["donation_item_id"]]
        assert item["estimated_weight_lbs"] == lot["received_lbs"]
        assert item["category_id"] == lot["category_id"]


def test_the_donations_are_confirmed_and_labelled_as_seeded_stock(data):
    for d in data.current_donations:
        assert d["status"] == "confirmed" and d["source_type"] == "historical"
        assert d["original_filename"] == "seeded-current-inventory"
    assert (
        max(
            len([i for i in data.current_donation_items if i["donation_id"] == d["id"]])
            for d in data.current_donations
        )
        <= 4
    )


# --- loading it -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded(migrated_engine):
    full = add_current_inventory(generate(DEFAULT_SEED))
    load(migrated_engine, full, PASSWORDS)
    yield full
    truncate_app_tables(migrated_engine)


def scalar(engine, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def test_loading_adds_the_current_lots_as_available_stock(migrated_engine, loaded):
    assert scalar(
        migrated_engine, "SELECT count(*) FROM inventory_lots WHERE status = 'available'"
    ) == len(loaded.current_lots)
    assert scalar(migrated_engine, "SELECT count(*) FROM inventory_lots") == len(
        loaded.inventory_lots
    ) + len(loaded.current_lots)
    assert float(
        scalar(migrated_engine, "SELECT sum(remaining_lbs) FROM inventory_lots")
    ) == pytest.approx(sum(lot["received_lbs"] for lot in loaded.current_lots), rel=1e-6)
    assert scalar(
        migrated_engine,
        "SELECT count(*) FROM donations WHERE original_filename = 'seeded-current-inventory'",
    ) == len(loaded.current_donations)


def test_ids_keep_counting_after_the_seed_so_new_intake_does_not_collide(migrated_engine, loaded):
    with migrated_engine.begin() as conn:
        new_id = conn.execute(
            text(
                "INSERT INTO donors (name, donor_type) VALUES ('Another Donor', 'other') RETURNING id"
            )
        ).scalar_one()
        conn.rollback()
    assert new_id > len(loaded.donors)
    max_lot = scalar(migrated_engine, "SELECT max(id) FROM inventory_lots")
    assert max_lot == max(lot["id"] for lot in loaded.current_lots)
