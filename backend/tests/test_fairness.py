"""The fairness measure: share of P50 demand met per group, and which group is furthest below."""

import numpy as np
import pandas as pd
import pytest

from eval import fairness


def pantry_frame(n=6):
    pan = pd.DataFrame(
        {
            "id": range(1, n + 1),
            "county": ["A", "A", "B", "B", "C", "C"][:n],
            "households": [100, 200, 300, 400, 500, 600][:n],
        }
    )
    return fairness.label_groups(pan, [5.0, 10.0, 15.0, 20.0, 25.0, 30.0][:n])


def test_groups_are_terciles_of_miles_and_households():
    pan = pantry_frame()
    assert list(pan.distance) == ["near", "near", "middle", "middle", "far", "far"]
    assert list(pan["size"]) == ["small", "small", "medium", "medium", "large", "large"]


def test_share_is_met_over_p50_and_gap_is_in_points_to_the_overall_share():
    pan = pantry_frame()
    met = np.array([100, 100, 100, 100, 0, 0])
    p50 = np.array([100, 100, 100, 100, 100, 100])
    tables = fairness.group_tables(pan, met, p50)
    far = tables["distance"].loc["far"]
    assert far.share == pytest.approx(0.0)
    assert far.gap_pp == pytest.approx(-66.667, abs=0.01)  # overall share is 4/6
    assert tables["distance"].loc["near"].gap_pp == pytest.approx(33.333, abs=0.01)


def test_worst_gap_names_the_dimension_and_group():
    pan = pantry_frame()
    met = np.array([100, 100, 100, 100, 0, 0])
    tables = fairness.group_tables(pan, met, np.full(6, 100))
    dimension, group, gap = fairness.worst_gap(tables)
    assert gap == pytest.approx(-66.667, abs=0.01)
    assert (dimension, group) in {("distance", "far"), ("county", "C")}


def test_equal_shares_everywhere_pass_the_ten_point_rule():
    pan = pantry_frame()
    scenario = fairness._scenario("equal", pan, np.full(6, 60.0), np.full(6, 100.0))
    assert scenario.passes and scenario.worst[2] == pytest.approx(0.0, abs=1e-9)
    assert scenario.overall == pytest.approx(0.6) and scenario.worst_pantry == pytest.approx(0.6)


def test_a_group_eleven_points_below_average_fails():
    pan = pantry_frame()
    met = np.array([100.0, 100.0, 100.0, 100.0, 60.0, 60.0])  # far band at 60%, average 86.7%
    scenario = fairness._scenario("short", pan, met, np.full(6, 100.0))
    assert not scenario.passes


def test_pantries_with_no_forecast_do_not_break_the_shares():
    pan = pantry_frame()
    scenario = fairness._scenario(
        "empty", pan, np.zeros(6), np.array([0, 100, 100, 100, 100, 100.0])
    )
    assert scenario.worst_pantry == 0.0
