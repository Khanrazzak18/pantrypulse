"""The generator is a pure function of its seed, and its output has the shape CLAUDE.md asks for."""

from collections import Counter, defaultdict
from datetime import date, timedelta

import numpy as np
import pytest

from app.constants import CATEGORY_NAMES, COUNTIES, PERISHABLE_CATEGORIES
from scripts.generate_synthetic_data import DEFAULT_SEED, N_PANTRIES, N_WEEKS, fingerprint, generate

LAST_WEEK = date(2026, 9, 28)


@pytest.fixture(scope="module")
def data():
    return generate(DEFAULT_SEED)


# --- reproducibility ----------------------------------------------------------------------


def test_same_seed_gives_identical_data(data):
    assert fingerprint(generate(DEFAULT_SEED)) == fingerprint(data)


def test_different_seed_gives_different_data(data):
    assert fingerprint(generate(DEFAULT_SEED + 1)) != fingerprint(data)


# --- shape --------------------------------------------------------------------------------


def test_85_pantries_in_6_counties_and_pantry_14_exists(data):
    assert len(data.pantries) == N_PANTRIES == 85
    assert {p["county"] for p in data.pantries} == set(COUNTIES)
    assert len(COUNTIES) == 6
    by_id = {p["id"]: p for p in data.pantries}
    assert by_id[14]["name"] == "Pantry 14"
    assert len({p["name"] for p in data.pantries}) == 85


def test_baseline_households_total_about_40000_a_month(data):
    total = sum(p["baseline_households"] for p in data.pantries)
    assert 38_000 <= total <= 42_000


def test_three_years_of_consecutive_monday_weeks(data):
    weeks = sorted({d["week_start"] for d in data.distributions})
    assert len(weeks) == N_WEEKS == 156
    assert weeks[-1] == LAST_WEEK
    assert all(w.isoweekday() == 1 for w in weeks)
    assert all(b - a == timedelta(weeks=1) for a, b in zip(weeks, weeks[1:], strict=False))


def test_one_distribution_row_per_pantry_category_week(data):
    assert len(data.distributions) == 85 * 8 * 156
    keys = {(d["pantry_id"], d["category_id"], d["week_start"]) for d in data.distributions}
    assert len(keys) == len(data.distributions)
    assert {d["category_id"] for d in data.distributions} == set(range(1, 9))


def test_distribution_values_are_sane(data):
    assert all(d["lbs"] >= 0 for d in data.distributions)
    assert all(d["households"] > 0 for d in data.distributions)
    total_per_week = np.mean(
        list(_sum_by(data.distributions, lambda d: d["week_start"], "lbs").values())
    )
    # ~40k households a month at ~35 lb each is roughly 300k lb a week across the network
    assert 150_000 <= total_per_week <= 450_000


def test_households_are_the_same_across_categories_of_a_pantry_week(data):
    seen = defaultdict(set)
    for d in data.distributions:
        seen[(d["pantry_id"], d["week_start"])].add(d["households"])
    assert all(len(v) == 1 for v in seen.values())


# --- weather, holidays, benefits ----------------------------------------------------------


def test_weekly_context_covers_every_county_and_week(data):
    assert len(data.weekly_context) == 6 * 156
    keys = {(c["county"], c["week_start"]) for c in data.weekly_context}
    assert len(keys) == len(data.weekly_context)


def test_weather_is_seasonal_and_plausible(data):
    july = [c["avg_temp_f"] for c in data.weekly_context if c["week_start"].month == 7]
    january = [c["avg_temp_f"] for c in data.weekly_context if c["week_start"].month == 1]
    assert np.mean(july) > np.mean(january) + 25
    assert all(-20 <= c["avg_temp_f"] <= 110 for c in data.weekly_context)
    assert all(c["precip_in"] >= 0 for c in data.weekly_context)


def test_school_holidays_and_benefit_weeks_occur_at_realistic_rates(data):
    n = len(data.weekly_context)
    holiday_share = sum(c["school_holiday"] for c in data.weekly_context) / n
    benefit_share = sum(c["benefit_week"] for c in data.weekly_context) / n
    assert 0.15 <= holiday_share <= 0.40
    assert 0.18 <= benefit_share <= 0.30


# --- donations, lots, spoilage ------------------------------------------------------------


def test_lots_link_to_items_and_match_their_weight(data):
    items = {i["id"]: i for i in data.donation_items}
    donations = {d["id"] for d in data.donations}
    assert all(i["donation_id"] in donations for i in data.donation_items)
    for lot in data.inventory_lots:
        assert lot["received_lbs"] > 0
        assert items[lot["donation_item_id"]]["estimated_weight_lbs"] == lot["received_lbs"]
        assert 0 <= lot["expired_lbs"] <= lot["received_lbs"]
        assert lot["remaining_lbs"] == 0  # history is closed: everything was used or expired
    assert {d["source_type"] for d in data.donations} == {"historical"}


def test_perishable_lots_have_3_to_7_day_shelf_life_unless_frozen(data):
    perishable_ids = {i + 1 for i, n in enumerate(CATEGORY_NAMES) if n in PERISHABLE_CATEGORIES}
    fresh = [
        lot for lot in data.inventory_lots
        if lot["category_id"] in perishable_ids and lot["storage_type"] != "frozen"
    ]  # fmt: skip
    assert fresh
    for lot in fresh:
        days = (lot["expiry_date"] - lot["received_date"]).days
        assert 3 <= days <= 7


def test_nearly_half_of_received_pounds_are_perishable(data):
    perishable_ids = {i + 1 for i, n in enumerate(CATEGORY_NAMES) if n in PERISHABLE_CATEGORIES}
    total = sum(lot["received_lbs"] for lot in data.inventory_lots)
    perishable = sum(
        lot["received_lbs"] for lot in data.inventory_lots if lot["category_id"] in perishable_ids
    )
    assert 0.40 <= perishable / total <= 0.60


def test_perishable_spoilage_is_about_12_percent(data):
    perishable_ids = {i + 1 for i, n in enumerate(CATEGORY_NAMES) if n in PERISHABLE_CATEGORIES}
    lots = [lot for lot in data.inventory_lots if lot["category_id"] in perishable_ids]
    rate = sum(lot["expired_lbs"] for lot in lots) / sum(lot["received_lbs"] for lot in lots)
    assert 0.105 <= rate <= 0.135


def test_spoilage_is_stable_year_by_year(data):
    perishable_ids = {i + 1 for i, n in enumerate(CATEGORY_NAMES) if n in PERISHABLE_CATEGORIES}
    start = LAST_WEEK - timedelta(weeks=155)
    by_year = defaultdict(lambda: [0.0, 0.0])
    for lot in data.inventory_lots:
        if lot["category_id"] in perishable_ids:
            year = (lot["received_date"] - start).days // 365
            by_year[year][0] += lot["expired_lbs"]
            by_year[year][1] += lot["received_lbs"]
    for expired, received in by_year.values():
        assert 0.09 <= expired / received <= 0.15


# --- shortages ----------------------------------------------------------------------------


def test_about_one_in_four_pantries_report_a_shortage_each_week(data):
    pairs = {(r["pantry_id"], r["week_start"]) for r in data.shortage_reports}
    rate = len(pairs) / (N_PANTRIES * N_WEEKS)
    assert 0.20 <= rate <= 0.30


def test_every_week_has_some_shortage_reports(data):
    weeks = Counter(r["week_start"] for r in data.shortage_reports)
    assert len(weeks) == N_WEEKS


def test_shortages_are_weighted_toward_protein_and_produce(data):
    ids = {name: i + 1 for i, name in enumerate(CATEGORY_NAMES)}
    top = sum(r["category_id"] in (ids["protein"], ids["produce"]) for r in data.shortage_reports)
    assert top / len(data.shortage_reports) >= 0.60


def test_shortage_reports_are_well_formed_and_unique(data):
    keys = {(r["pantry_id"], r["category_id"], r["week_start"]) for r in data.shortage_reports}
    assert len(keys) == len(data.shortage_reports)
    assert all(r["severity"] in (1, 2, 3) for r in data.shortage_reports)
    assert all(r["households_turned_away"] >= 0 for r in data.shortage_reports)
    assert all(r["week_start"].isoweekday() == 1 for r in data.shortage_reports)


def test_shortage_weeks_show_censored_demand(data):
    """Within each category, pantries that reported a shortage got less per household."""
    reported = {(r["pantry_id"], r["category_id"], r["week_start"]) for r in data.shortage_reports}
    short, normal = defaultdict(list), defaultdict(list)
    for d in data.distributions:
        key = (d["pantry_id"], d["category_id"], d["week_start"])
        (short if key in reported else normal)[d["category_id"]].append(d["lbs"] / d["households"])
    ratios = [np.mean(short[c]) / np.mean(normal[c]) for c in short if len(short[c]) >= 50]
    assert len(ratios) >= 2
    assert np.mean(ratios) < 0.9


def _sum_by(rows, key, field):
    out = defaultdict(float)
    for row in rows:
        out[key(row)] += row[field]
    return out
