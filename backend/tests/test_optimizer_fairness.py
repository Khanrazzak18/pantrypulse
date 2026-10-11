"""When stock is short, every pantry gets a fair share of its forecast demand.

Before tiered coverage, all pantries earned the same per pound, so the only thing that separated
them was the small distance penalty and the nearest pantries were filled completely before a far
one received anything. These tests use a small scarce-stock fixture to prove that no longer happens.
"""

from datetime import date, timedelta

import pytest

from app.services.optimizer import DemandIn, LotIn, OptimizerParams, PantryIn, solve

DELIVERY = date(2026, 10, 7)
NEAR, MIDDLE, FAR = 1, 2, 3


def stock(lbs: float, category: int = 1) -> list[LotIn]:
    return [LotIn(1, category, "ambient", lbs, DELIVERY + timedelta(days=5))]


def pantries(miles=(5.0, 20.0, 35.0)) -> list[PantryIn]:
    return [PantryIn(i + 1, m, 10_000.0, 10_000.0) for i, m in enumerate(miles)]


def wants(p50=(100.0, 100.0, 100.0), over=1.2) -> dict:
    return {(i + 1, 1): DemandIn(v, v * over) for i, v in enumerate(p50)}


def shares(solution, p50=(100.0, 100.0, 100.0)) -> list[float]:
    got = {i: 0.0 for i in (1, 2, 3)}
    for s in solution.shipments:
        got[s.pantry_id] += s.lbs
    return [min(got[i + 1], p50[i]) / p50[i] for i in range(3)]


def test_scarce_stock_is_spread_by_share_of_demand_not_filled_nearest_first():
    solution = solve(stock(100.0), pantries(), wants(), DELIVERY)
    near, middle, far = shares(solution)
    assert far >= 0.30, f"the far pantry got {far:.0%} of its demand"
    assert max(near, middle, far) - min(near, middle, far) <= 0.10 + 1e-9
    assert sum(s.lbs for s in solution.shipments) == pytest.approx(
        100.0, abs=0.05
    )  # all of it used


def test_a_far_pantry_is_not_starved_when_stock_is_a_fifth_of_demand():
    solution = solve(stock(60.0), pantries(), wants(), DELIVERY)
    assert min(shares(solution)) >= 0.15


def test_bigger_pantries_get_more_pounds_but_the_same_share():
    p50 = (50.0, 100.0, 300.0)  # the far pantry is the biggest
    solution = solve(stock(180.0), pantries(), wants(p50), DELIVERY)
    near, middle, far = shares(solution, p50)
    assert max(near, middle, far) - min(near, middle, far) <= 0.10 + 1e-9
    lbs = {s.pantry_id: s.lbs for s in solution.shipments}
    assert lbs[FAR] > lbs[MIDDLE] > lbs[NEAR]


def test_distance_never_outweighs_unmet_demand_however_large_the_penalty():
    heavy = OptimizerParams(distance_penalty_per_mile=0.5)  # 1000 times the default
    solution = solve(stock(100.0), pantries(), wants(), DELIVERY, heavy)
    near, middle, far = shares(solution)
    assert far >= 0.30
    assert max(near, middle, far) - min(near, middle, far) <= 0.10 + 1e-9


def test_with_enough_stock_every_pantry_still_gets_its_full_forecast():
    solution = solve(stock(1000.0), pantries(), wants(), DELIVERY)
    assert shares(solution) == [1.0, 1.0, 1.0]


def test_distance_still_breaks_ties_between_equally_covered_pantries():
    # same share for everyone is reached first; what is left over goes to the nearest pantries
    solution = solve(stock(95.0), pantries(), wants(), DELIVERY)
    near, middle, far = shares(solution)
    assert near >= middle >= far


def test_two_pantries_with_equal_need_end_up_within_ten_points_of_each_other_at_any_distance():
    solution = solve(stock(80.0), pantries((9.0, 36.0, 36.0)), wants(), DELIVERY)
    shares_ = shares(solution)
    assert max(shares_) - min(shares_) <= 0.10 + 1e-9


def test_demand_met_is_still_reported_and_never_exceeds_the_forecast():
    solution = solve(stock(100.0), pantries(), wants(), DELIVERY)
    assert solution.demand_met_p50 == pytest.approx(100.0, abs=0.05)
    assert solution.demand_met_p50 <= 300.0 + 1e-6


def test_one_tier_is_the_old_objective_and_fills_the_nearest_pantry_first():
    """The 'before' in docs/eval/fairness.md: coverage_tiers=1 gives every pound the same reward."""
    solution = solve(stock(100.0), pantries(), wants(), DELIVERY, OptimizerParams(coverage_tiers=1))
    near, middle, far = shares(solution)
    assert near == pytest.approx(1.0, abs=0.01) and far == pytest.approx(0.0, abs=0.01)
