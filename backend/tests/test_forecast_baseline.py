"""Seasonal naive: the forecast for a week is what was observed the same week last year."""

import numpy as np
import pandas as pd

from app.services import forecasting as fc
from tests.forecast_fixtures import make_panel, week_of

N = 110


def test_baseline_is_the_observed_value_52_weeks_earlier():
    panel = make_panel(
        pantries=(1, 2), categories=(1,), n_weeks=N, lbs_fn=lambda p, c, k: 1000 * p + k
    )
    frame = fc.build_frame(panel, week_of(N, N))  # forecast the week after the data
    features = fc.build_features(frame)
    target = features[features.week_start == pd.Timestamp(week_of(N, N))].set_index("pantry_id")
    # target week index is N; 52 weeks earlier is index N - 52
    assert target.loc[1, "baseline_lbs"] == 1000 * 1 + (N - 52)
    assert target.loc[2, "baseline_lbs"] == 1000 * 2 + (N - 52)


def test_baseline_has_nothing_to_say_for_the_first_year():
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=N, lbs_fn=lambda p, c, k: k)
    features = fc.build_features(fc.build_frame(panel, week_of(N, N)))
    first_year = features[features.week_start < pd.Timestamp(week_of(52, N))]
    assert first_year.baseline_lbs.isna().all()
    assert features.baseline_lbs.notna().sum() == N + 1 - 52


def test_baseline_uses_what_was_observed_not_the_corrected_demand():
    panel = make_panel(
        pantries=(1,), categories=(1,), n_weeks=N, lbs_fn=lambda p, c, k: 100.0 + k,
        shortages=[(1, 1, 30, 3, 80)],
    )  # fmt: skip
    features = fc.build_features(fc.build_frame(panel, week_of(N, N)))
    row = features[features.week_start == pd.Timestamp(week_of(30 + 52, N))]
    assert row.baseline_lbs.iloc[0] == 100.0 + 30  # last year's observed pounds, uncorrected


def test_baseline_never_peeks_forward():
    """Baseline for week s only depends on week s - 52, so changing later weeks cannot matter."""
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=N, lbs_fn=lambda p, c, k: float(k))
    changed = panel.copy()
    changed.loc[changed.week_start >= pd.Timestamp(week_of(100, N)), "lbs"] = 9e9
    a = fc.build_features(
        fc.build_frame(panel[panel.week_start < pd.Timestamp(week_of(100, N))], week_of(100, N))
    )
    b = fc.build_features(
        fc.build_frame(changed[changed.week_start < pd.Timestamp(week_of(100, N))], week_of(100, N))
    )
    assert np.array_equal(a.baseline_lbs.to_numpy(), b.baseline_lbs.to_numpy(), equal_nan=True)
