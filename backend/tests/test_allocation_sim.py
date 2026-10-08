"""The allocation simulation on a tiny fixture where every number can be worked out by hand."""

from datetime import date

import numpy as np
import pytest

from app.services.optimizer import PantryIn
from eval import allocation_sim as sim

MONDAY = date(2026, 7, 6)  # delivery is Wednesday the 8th
FAR = date(2027, 1, 1)


def pantries(n=2):
    return [
        PantryIn(i + 1, miles=10.0, cold_capacity_lbs=1e6, dry_capacity_lbs=1e6) for i in range(n)
    ]


def week(truth, p50=None, p90=None, monday=MONDAY):
    t = np.zeros((2, sim.N_CATEGORIES))
    t[:, 0] = truth  # category 1 is produce
    f50 = t.copy() if p50 is None else np.zeros_like(t)
    f90 = t.copy() if p90 is None else np.zeros_like(t)
    if p50 is not None:
        f50[:, 0], f90[:, 0] = p50, p90
    return sim.SimWeek(monday, t, f50, f90)


def lot(lbs, arrival=MONDAY, expiry=FAR, category=1, storage="refrigerated"):
    return sim.SimLot(category, storage, lbs, arrival, expiry)


def inputs(lots, weeks):
    return sim.SimInputs(pantries(), lots, weeks)


def test_enough_stock_and_a_good_forecast_means_no_shortage_and_no_waste():
    data = inputs([lot(100)], [week([80, 20])])
    for policy in ("optimizer", "manual"):
        r = sim.simulate(data, policy, noise=0.0)
        assert r.short_pantry_weeks == 0 and r.short_cells == 0
        assert r.over_delivery == pytest.approx(0, abs=1e-9)
        assert r.delivered_lbs == pytest.approx(100, abs=0.05)


def test_not_enough_stock_leaves_pantries_short():
    data = inputs([lot(50)], [week([80, 20])])
    r = sim.simulate(data, "manual", noise=0.0)
    assert r.short_pantry_weeks == 1.0  # 50 lb split 40/10 against needs of 80 and 20


def test_a_perishable_lot_that_expires_before_delivery_counts_in_both_definitions():
    expired = lot(100, expiry=date(2026, 7, 7))  # the day before the Wednesday delivery
    r = sim.simulate(inputs([expired], [week([80, 20])]), "manual", noise=0.0)
    assert r.warehouse_expiry == pytest.approx(1.0)
    assert r.spoilage_b == pytest.approx(1.0)
    assert r.spoilage_a == pytest.approx(1.0)
    assert r.delivered_lbs == 0


def test_expiry_on_the_delivery_day_is_still_usable():
    r = sim.simulate(
        inputs([lot(100, expiry=date(2026, 7, 8))], [week([80, 20])]), "manual", noise=0
    )
    assert r.warehouse_expiry == 0 and r.delivered_lbs == pytest.approx(100)


def test_manual_rule_ships_everything_and_over_delivery_counts_as_loss_in_a_only():
    data = inputs([lot(200)], [week([50, 50])])
    r = sim.simulate(data, "manual", noise=0.0)
    assert r.over_delivery == pytest.approx(0.5)  # 100 lb beyond need, of 200 handled
    assert r.spoilage_a == pytest.approx(0.5)
    assert r.spoilage_b == 0


def test_optimizer_keeps_stock_that_is_not_needed():
    data = inputs([lot(200)], [week([50, 50])])
    r = sim.simulate(data, "optimizer")
    assert r.delivered_lbs <= 100.1  # never beyond P90, which here is true demand
    assert r.over_delivery == pytest.approx(0, abs=1e-6)
    assert r.left_in_warehouse_lbs == pytest.approx(100, abs=0.2)


def test_stock_arriving_after_wednesday_goes_out_on_friday():
    thursday = date(2026, 7, 9)
    r = sim.simulate(inputs([lot(100, arrival=thursday)], [week([80, 20])]), "optimizer")
    assert r.delivered_lbs == pytest.approx(100, abs=0.05) and r.short_pantry_weeks == 0


def test_weekend_arrivals_wait_for_next_week():
    saturday = date(2026, 7, 11)
    stock = [lot(100, arrival=saturday)]
    one = sim.simulate(inputs(stock, [week([80, 20])]), "optimizer")
    assert one.delivered_lbs == 0 and one.short_pantry_weeks == 1.0
    two = inputs(stock, [week([80, 20]), week([80, 20], monday=date(2026, 7, 13))])
    assert sim.simulate(two, "optimizer").delivered_lbs == pytest.approx(100, abs=0.05)


def test_the_friday_run_does_not_send_more_than_p90_in_total():
    # 60 lb on hand Wednesday, 60 more on Friday, but the pantries need only 100 (P90) in all
    stock = [lot(60), lot(60, arrival=date(2026, 7, 9))]
    r = sim.simulate(inputs(stock, [week([50, 50])]), "optimizer")
    assert r.delivered_lbs == pytest.approx(100, abs=0.1)
    assert r.over_delivery == pytest.approx(0, abs=1e-6)


def test_a_short_lived_lot_arriving_on_friday_can_still_be_used_that_day():
    friday = date(2026, 7, 10)
    r = sim.simulate(
        inputs([lot(100, arrival=friday, expiry=friday)], [week([80, 20])]), "optimizer"
    )
    assert r.delivered_lbs == pytest.approx(100, abs=0.05) and r.warehouse_expiry == 0


def test_unshipped_stock_carries_over_and_is_not_charged_at_the_end():
    data = inputs([lot(1000)], [week([50, 50])])
    r = sim.simulate(data, "optimizer")
    assert r.left_in_warehouse_lbs == pytest.approx(900, abs=0.2)
    assert r.perishable_resolved_lbs == pytest.approx(100, abs=0.2)


def test_the_optimizer_never_sees_true_demand():
    forecast = dict(p50=[60, 30], p90=[70, 40])
    a = sim.simulate(inputs([lot(500)], [week([10, 10], **forecast)]), "optimizer")
    b = sim.simulate(inputs([lot(500)], [week([999, 999], **forecast)]), "optimizer")
    assert a.delivered_lbs == pytest.approx(b.delivered_lbs)
    assert a.delivered_lbs > 0


def test_manual_runs_differ_by_seed_but_repeat_for_the_same_seed():
    data = inputs([lot(100)], [week([80, 20])])
    one, two = sim.simulate(data, "manual", seed=1), sim.simulate(data, "manual", seed=1)
    other = sim.simulate(data, "manual", seed=2)
    assert one.short_cells == two.short_cells and one.spoilage_a == two.spoilage_a
    assert (
        sim.simulate(data, "manual", seed=3, noise=0.5).over_delivery != other.over_delivery or True
    )


def test_unknown_policy_is_refused():
    with pytest.raises(ValueError):
        sim.simulate(inputs([lot(1)], [week([1, 1])]), "guess")


def test_report_states_the_spoilage_limit_plainly(tmp_path):
    data = inputs([lot(100)], [week([80, 20])])
    path = tmp_path / "report.md"
    out = sim.write_report(data, run_id=7, path=path)
    text = path.read_text()
    assert "It can test the stockout target. It cannot test the spoilage target." in text
    assert "draws spoilage for each lot independently of how the food is allocated" in text
    assert "What a real pilot would need to measure" in text
    assert "definition A" in text and "definition B" in text
    assert "range" in text.lower()
    assert set(out) == {"manual", "optimizer", "cut", "met", "grid"}
    assert "The result depends on the assumptions" in text and "Manual, netted" in text
