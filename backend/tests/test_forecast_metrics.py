import numpy as np
import pandas as pd
import pytest

from app.services import forecasting as fc


def test_wape_is_total_absolute_error_over_total_actual():
    assert fc.wape([100, 200], [110, 180]) == pytest.approx(30 / 300)


def test_a_perfect_forecast_has_zero_wape():
    assert fc.wape([5, 6, 7], [5, 6, 7]) == 0.0


def test_pairs_with_a_missing_value_are_ignored():
    assert fc.wape([100, np.nan, 200], [110, 5, 180]) == pytest.approx(0.1)
    assert fc.wape([100, 200, 300], [110, 180, np.nan]) == pytest.approx(30 / 300)


def test_wape_is_undefined_when_there_is_nothing_to_score():
    assert np.isnan(fc.wape([0, 0], [1, 2]))
    assert np.isnan(fc.wape([np.nan], [1]))


def frame():
    return pd.DataFrame(
        {
            "pantry_id": [1, 1, 2, 2],
            "category_id": [1, 1, 1, 1],
            "lbs": [100.0, 100.0, 1000.0, 1000.0],
            "p10": [80.0, 150.0, 900.0, 900.0],
            "p50": [110.0, 90.0, 1100.0, 1000.0],
            "p90": [120.0, 160.0, 1200.0, 1050.0],
        }
    )


def test_wape_by_series_scores_each_pantry_and_category_on_its_own():
    by_series = fc.wape_by_series(frame(), "p50")
    assert by_series[(1, 1)] == pytest.approx(20 / 200)
    assert by_series[(2, 1)] == pytest.approx(100 / 2000)


def test_overall_wape_weights_big_series_more_than_the_average_of_series():
    df = frame()
    overall = fc.wape(df.lbs, df.p50)
    average = fc.wape_by_series(df, "p50").mean()
    assert overall == pytest.approx(120 / 2200)
    assert overall != pytest.approx(average)


def test_interval_coverage_counts_actuals_inside_the_band_inclusive():
    df = frame()
    # row 0: 100 in [80,120] yes; row 1: 100 in [150,160] no; row 2: 1000 in [900,1200] yes;
    # row 3: 1000 in [900,1050] yes
    assert fc.interval_coverage(df.lbs, df.p10, df.p90) == pytest.approx(3 / 4)
    assert fc.interval_coverage([5.0], [5.0], [5.0]) == 1.0


def test_share_of_series_below_a_threshold():
    series = pd.Series([0.05, 0.19, 0.20, 0.35, np.nan])
    assert fc.share_below(series, 0.20) == pytest.approx(2 / 4)  # NaN is not a series
