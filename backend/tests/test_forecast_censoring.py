"""Observed pounds are capped by supply in shortage weeks. The correction raises only those."""

import numpy as np
import pytest

from app.services import forecasting as fc
from tests.forecast_fixtures import make_panel


@pytest.mark.parametrize(
    ("severity", "turned_away", "households", "expected"),
    [
        (1, 0, 100, 0.10),  # minor: the prior
        (2, 0, 100, 0.25),
        (3, 0, 100, 0.50),  # ran out
        (1, 40, 100, 0.40),  # many households turned away: the evidence beats the prior
        (2, 10, 100, 0.25),  # little evidence: the prior stands
        (1, 90, 100, 0.50),  # never claim more than half was unmet
        (3, 500, 100, 0.50),
        (2, 5, 0, 0.50),  # zero visits is safe (treated as one household)
    ],
)
def test_shortfall_combines_the_severity_prior_with_the_share_of_households_turned_away(
    severity, turned_away, households, expected
):
    assert fc.censoring_shortfall(severity, turned_away, households) == pytest.approx(expected)


def test_a_missing_report_means_no_shortfall():
    assert fc.censoring_shortfall(np.nan, np.nan, 100) == 0.0


def test_the_correction_applies_to_shortage_weeks_only():
    panel = make_panel(lbs_fn=lambda p, c, k: 500.0, shortages=[(2, 1, 40, 2, 0)])
    out = fc.apply_censoring_correction(panel)
    hit = (
        (out.pantry_id == 2)
        & (out.category_id == 1)
        & (out.week_start == panel.week_start.iloc[40])
    )
    assert out.loc[hit, "demand_adj"].iloc[0] == pytest.approx(500 / (1 - 0.25))
    assert out.loc[hit, "shortfall"].iloc[0] == pytest.approx(0.25)
    # every other row, including the same pantry's other category that week, is untouched
    assert (out.loc[~hit, "demand_adj"] == out.loc[~hit, "lbs"]).all()
    assert (out.loc[~hit, "shortfall"] == 0).all()
    assert out["has_report"].sum() == 1


def test_a_report_in_another_week_or_category_does_not_leak_onto_its_neighbours():
    panel = make_panel(lbs_fn=lambda p, c, k: 100.0, shortages=[(1, 1, 10, 3, 0)])
    out = fc.apply_censoring_correction(panel)
    changed = out[out.demand_adj != out.lbs]
    assert len(changed) == 1
    assert (changed.pantry_id.iloc[0], changed.category_id.iloc[0]) == (1, 1)


def test_worse_shortages_get_a_bigger_uplift():
    uplift = []
    for severity in (1, 2, 3):
        panel = make_panel(lbs_fn=lambda p, c, k: 100.0, shortages=[(1, 1, 5, severity, 0)])
        out = fc.apply_censoring_correction(panel)
        uplift.append(out.demand_adj.max())
    assert uplift[0] < uplift[1] < uplift[2]


def test_the_correction_can_be_switched_off_for_the_ablation():
    panel = make_panel(shortages=[(1, 1, 5, 3, 50)])
    out = fc.apply_censoring_correction(panel, enabled=False)
    assert (out.demand_adj == out.lbs).all()
    assert (
        out.has_report.sum() == 1
    )  # the report is still known; it just does not change the target


def test_the_input_panel_is_not_modified():
    panel = make_panel(shortages=[(1, 1, 5, 3, 50)])
    before = panel.copy()
    fc.apply_censoring_correction(panel)
    assert panel.equals(before)
