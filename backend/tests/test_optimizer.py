"""The allocation LP: what it may never do, and what it should prefer."""

import time
from datetime import date, timedelta

import numpy as np
import pytest

from app.services.optimizer import (
    DemandIn,
    LotIn,
    OptimizerParams,
    PantryIn,
    haversine_miles,
    solve,
)

DELIVERY = date(2026, 10, 7)
TOL = 1e-6


def lot(id, category=1, rem=100.0, days=5, storage="refrigerated"):
    expiry = None if days is None else DELIVERY + timedelta(days=days)
    return LotIn(id, category, storage, rem, expiry)


def pantry(id, miles=10.0, cold=10_000.0, dry=10_000.0):
    return PantryIn(id, miles, cold, dry)


def demand(pairs: dict) -> dict:
    return {key: DemandIn(*value) for key, value in pairs.items()}


def shipped(solution, **by):
    return sum(s.lbs for s in solution.shipments if all(getattr(s, k) == v for k, v in by.items()))


# --- distance ---------------------------------------------------------------------------------


def test_haversine_matches_known_distances():
    assert haversine_miles(40.0, -83.0, 40.0, -83.0) == 0.0
    # one degree of longitude at 40 degrees north is about 53 miles
    assert haversine_miles(40.0, -83.0, 40.0, -82.0) == pytest.approx(53.0, abs=0.6)
    # one degree of latitude is about 69 miles
    assert haversine_miles(40.0, -83.0, 41.0, -83.0) == pytest.approx(69.1, abs=0.3)
    assert haversine_miles(40.0, -83.0, 39.7, -82.6) == haversine_miles(39.7, -82.6, 40.0, -83.0)


# --- hard limits ---------------------------------------------------------------------------------


def random_instance(seed):
    rng = np.random.default_rng(seed)
    pantries = [
        pantry(
            p,
            float(rng.uniform(5, 40)),
            float(rng.uniform(200, 3000)),
            float(rng.uniform(200, 5000)),
        )
        for p in range(1, 13)
    ]
    storages = ["refrigerated", "frozen", "ambient"]
    lots = [
        lot(i, int(rng.integers(1, 5)), float(rng.uniform(100, 6000)), int(rng.integers(0, 12)),
            storages[int(rng.integers(0, 3))])
        for i in range(1, 11)
    ]  # fmt: skip
    wants = {}
    for p in pantries:
        for c in range(1, 5):
            p50 = float(rng.uniform(0, 900))
            wants[(p.id, c)] = (p50, p50 * float(rng.uniform(1.0, 1.4)))
    return lots, pantries, demand(wants)


@pytest.mark.parametrize("seed", range(25))
def test_a_solution_never_exceeds_supply_capacity_or_the_p90_cap(seed):
    lots, pantries, wants = random_instance(seed)
    solution = solve(lots, pantries, wants, DELIVERY)
    assert solution.status == "OPTIMAL"
    for item in lots:
        assert shipped(solution, lot_id=item.id) <= item.remaining_lbs + TOL, "lot oversubscribed"
    category = {item.id: item.category_id for item in lots}
    cold = {item.id: item.storage_type != "ambient" for item in lots}
    for p in pantries:
        mine = [s for s in solution.shipments if s.pantry_id == p.id]
        assert sum(s.lbs for s in mine if cold[s.lot_id]) <= p.cold_capacity_lbs + TOL
        assert sum(s.lbs for s in mine if not cold[s.lot_id]) <= p.dry_capacity_lbs + TOL
        for c in range(1, 5):
            assert sum(s.lbs for s in mine if category[s.lot_id] == c) <= wants[(p.id, c)].p90 + TOL
    assert all(s.lbs > 0 for s in solution.shipments)


def test_amounts_are_rounded_down_to_hundredths_never_up():
    lots = [lot(1, rem=100.0)]
    solution = solve(lots, [pantry(1)], demand({(1, 1): (33.3333, 33.3333)}), DELIVERY)
    (only,) = solution.shipments
    assert only.lbs <= 33.3333 and round(only.lbs, 2) == only.lbs


def test_frozen_and_refrigerated_lots_use_cold_space_and_ambient_uses_dry_space():
    lots = [lot(1, 1, 1000, storage="frozen"), lot(2, 2, 1000, storage="ambient")]
    wants = demand({(1, 1): (500, 500), (1, 2): (500, 500)})
    out = solve(lots, [pantry(1, cold=120.0, dry=300.0)], wants, DELIVERY)
    assert shipped(out, lot_id=1) == pytest.approx(120.0, abs=0.01)
    assert shipped(out, lot_id=2) == pytest.approx(300.0, abs=0.01)


def test_two_lots_of_one_category_together_stay_under_that_categorys_p90():
    lots = [lot(1, 1, 500), lot(2, 1, 500)]
    out = solve(lots, [pantry(1)], demand({(1, 1): (300, 400)}), DELIVERY)
    assert shipped(out, pantry_id=1) <= 400 + TOL


def test_nothing_is_sent_where_nothing_is_forecast():
    lots = [lot(1, 1, 500)]
    out = solve(
        lots, [pantry(1), pantry(2)], demand({(1, 1): (0, 0), (2, 1): (200, 250)}), DELIVERY
    )
    assert shipped(out, pantry_id=1) == 0 and shipped(out, pantry_id=2) > 0


# --- preferences ---------------------------------------------------------------------------------


def test_the_soonest_expiring_lot_ships_first_when_there_is_more_than_enough():
    lots = [lot(1, 1, 100, days=8), lot(2, 1, 100, days=2)]  # lot 2 expires first
    out = solve(lots, [pantry(1)], demand({(1, 1): (100, 100)}), DELIVERY)
    assert shipped(out, lot_id=2) == pytest.approx(100.0, abs=0.01)
    assert shipped(out, lot_id=1) == 0


def test_order_of_the_input_does_not_decide_which_lot_goes_first():
    a, b = lot(1, 1, 100, days=2), lot(2, 1, 100, days=8)
    for lots in ([a, b], [b, a]):
        out = solve(lots, [pantry(1)], demand({(1, 1): (100, 100)}), DELIVERY)
        assert shipped(out, lot_id=1) == pytest.approx(100.0, abs=0.01)


def test_with_a_shortage_all_of_the_stock_goes_out_and_the_nearer_pantry_is_filled_first():
    lots = [lot(1, 1, 150)]
    wants = demand({(1, 1): (100, 100), (2, 1): (100, 100)})
    out = solve(lots, [pantry(1, miles=30), pantry(2, miles=5)], wants, DELIVERY)
    assert shipped(out) == pytest.approx(150.0, abs=0.01)
    assert shipped(out, pantry_id=2) == pytest.approx(100.0, abs=0.01)  # the nearer pantry is whole
    assert shipped(out, pantry_id=1) == pytest.approx(50.0, abs=0.01)


def test_meeting_demand_beats_saving_distance():
    """A far pantry that needs food still gets it before a near pantry gets a surplus."""
    lots = [lot(1, 1, 100)]
    wants = demand({(1, 1): (100, 100), (2, 1): (0, 0)})
    out = solve(lots, [pantry(1, miles=36), pantry(2, miles=1)], wants, DELIVERY)
    assert shipped(out, pantry_id=1) == pytest.approx(100.0, abs=0.01)


def test_the_p50_to_p90_band_is_served_when_stock_allows_but_p50_comes_first():
    lots = [lot(1, 1, 150, days=9)]
    wants = demand({(1, 1): (100, 130), (2, 1): (100, 130)})
    out = solve(lots, [pantry(1), pantry(2)], wants, DELIVERY)
    # 150 lb of stock cannot cover both P50s (200), so no one is topped up past P50
    assert max(shipped(out, pantry_id=1), shipped(out, pantry_id=2)) <= 100 + 0.02
    plenty = solve([lot(1, 1, 1000, days=9)], [pantry(1), pantry(2)], wants, DELIVERY)
    assert shipped(plenty, pantry_id=1) == pytest.approx(130.0, abs=0.02)  # the band is filled


def test_without_the_band_reward_only_urgent_stock_goes_past_p50():
    wants = demand({(1, 1): (100, 130)})
    params = OptimizerParams(band_weight=0.0)
    calm = solve(
        [lot(1, 1, 1000, days=10)], [pantry(1)], wants, DELIVERY, params
    )  # at the horizon: no bonus
    urgent = solve([lot(1, 1, 1000, days=1)], [pantry(1)], wants, DELIVERY, params)
    assert shipped(calm) == pytest.approx(100.0, abs=0.02)
    assert shipped(urgent) == pytest.approx(130.0, abs=0.02)


# --- which lots are usable ------------------------------------------------------------------------


def test_lots_that_expire_before_delivery_are_left_out_and_reported():
    lots = [lot(1, 1, 100, days=-1), lot(2, 1, 100, days=0), lot(3, 1, 100, days=None)]
    out = solve(lots, [pantry(1)], demand({(1, 1): (300, 300)}), DELIVERY)
    assert out.excluded_lot_ids == [1]
    assert shipped(out, lot_id=1) == 0
    assert shipped(out, lot_id=2) > 0  # expiring on the delivery day is still usable
    assert shipped(out, lot_id=3) > 0  # no expiry date: shelf-stable


def test_lots_with_nothing_left_are_ignored():
    out = solve([lot(1, 1, 0.0)], [pantry(1)], demand({(1, 1): (100, 100)}), DELIVERY)
    assert out.shipments == [] and out.excluded_lot_ids == []


def test_no_lots_or_no_demand_is_an_empty_but_valid_answer():
    assert solve([], [pantry(1)], demand({(1, 1): (100, 100)}), DELIVERY).shipments == []
    assert solve([lot(1)], [pantry(1)], {}, DELIVERY).shipments == []
    assert solve([lot(1)], [], {}, DELIVERY).status == "OPTIMAL"


# --- repeatability and size --------------------------------------------------------------------------


def test_the_same_input_gives_the_same_answer():
    lots, pantries, wants = random_instance(3)
    a = solve(lots, pantries, wants, DELIVERY)
    b = solve(lots, pantries, wants, DELIVERY)
    assert [(s.lot_id, s.pantry_id, s.lbs) for s in a.shipments] == [
        (s.lot_id, s.pantry_id, s.lbs) for s in b.shipments
    ]


def test_a_full_size_problem_solves_in_well_under_a_second():
    rng = np.random.default_rng(0)
    pantries = [
        pantry(
            p,
            float(rng.uniform(9, 36)),
            float(rng.uniform(300, 12000)),
            float(rng.uniform(300, 22000)),
        )
        for p in range(1, 86)
    ]
    lots = [
        lot(
            i,
            (i % 8) + 1,
            float(rng.uniform(1500, 40000)),
            int(rng.integers(2, 12)),
            "refrigerated" if i % 8 < 3 else "ambient",
        )
        for i in range(1, 26)
    ]
    wants = demand(
        {(p.id, c): (float(rng.uniform(50, 1500)),) * 2 for p in pantries for c in range(1, 9)}
    )
    started = time.perf_counter()
    out = solve(lots, pantries, wants, DELIVERY)
    assert out.status == "OPTIMAL" and out.n_variables > 1000
    assert (
        time.perf_counter() - started < 3.0
    )  # the LP itself takes milliseconds; building it is the cost
    assert len(out.shipments) > 100


def test_the_solution_reports_how_much_forecast_demand_it_met():
    out = solve([lot(1, 1, 1000)], [pantry(1)], demand({(1, 1): (200, 250)}), DELIVERY)
    assert out.demand_met_p50 == pytest.approx(200.0, abs=0.02)
