"""Feature construction. The central rule: a feature for week t may only use data from before t
(plus the calendar, which is known in advance)."""

import numpy as np
import pandas as pd
import pytest

from app.services import forecasting as fc
from app.services.calendar_rules import benefit_week, school_holiday
from tests.forecast_fixtures import make_panel, week_of

N = 110
KEYS = ["pantry_id", "category_id", "week_start"]
# Raw current-week columns: none of these may be a model input.
CURRENT_WEEK_COLUMNS = {
    "lbs", "households", "severity", "turned_away", "temp", "precip", "demand_adj", "shortfall",
    "has_report", "baseline_lbs",
}  # fmt: skip


def features_for(panel, target_week):
    return fc.build_features(fc.build_frame(panel, target_week))


def at(df, week):
    return df[df.week_start == pd.Timestamp(week)]


# --- values -----------------------------------------------------------------------------------


def test_lags_and_rolling_means_on_a_ramp():
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=N, lbs_fn=lambda p, c, k: float(k))
    row = at(features_for(panel, week_of(N, N)), week_of(N, N)).iloc[0]
    assert [row.lag1, row.lag2, row.lag3, row.lag4] == [N - 1, N - 2, N - 3, N - 4]
    assert row.lag52 == N - 52
    assert row.rm4 == np.mean(
        [N - 4, N - 3, N - 2, N - 1]
    )  # the current week is not in its own mean
    assert row.rm12 == np.mean(range(N - 12, N))


def test_the_early_weeks_have_missing_lags_not_made_up_ones():
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=N, lbs_fn=lambda p, c, k: float(k))
    f = features_for(panel, week_of(N, N))
    first = at(f, week_of(0, N)).iloc[0]
    assert np.isnan(first.lag1) and np.isnan(first.rm4)
    assert np.isnan(at(f, week_of(3, N)).iloc[0].lag4)
    assert at(f, week_of(4, N)).iloc[0].lag4 == 0


def test_a_missing_week_leaves_a_gap_instead_of_shifting_older_values_forward():
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=60, lbs_fn=lambda p, c, k: float(k))
    panel = panel[panel.week_start != pd.Timestamp(week_of(50, 60))]
    f = features_for(panel, week_of(60, 60))
    assert np.isnan(at(f, week_of(51, 60)).iloc[0].lag1)  # week 50 is missing: no lag, not week 49
    assert at(f, week_of(51, 60)).iloc[0].lag2 == 49


def test_last_weeks_household_visits_and_shortage_history_are_features():
    panel = make_panel(
        pantries=(1,), categories=(1,), n_weeks=60, lbs_fn=lambda p, c, k: 100.0,
        shortages=[(1, 1, 55, 2, 10), (1, 1, 58, 3, 20)],
    )  # fmt: skip
    f = features_for(panel, week_of(60, 60))
    row = at(f, week_of(59, 60)).iloc[0]
    assert row.short_lag1 == 1  # a report in week 58, the week just before
    assert row.short_cnt4 == 2  # weeks 55 to 58 held two reports
    assert row.shortfall_lag1 == pytest.approx(0.50)
    assert row.hh_lag1 == 100.0 * 1 + (58 % 5)
    row60 = at(f, week_of(60, 60)).iloc[0]
    assert row60.short_lag1 == 0 and row60.short_cnt4 == 1


def test_weather_features_are_last_weeks_weather_and_the_climatology():
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=120)
    first = panel.week_start.min()
    panel["temp"] = ((panel.week_start - first) / pd.Timedelta(weeks=1)).astype(float)
    f = features_for(panel, week_of(120, 120))
    row = at(f, week_of(120, 120)).iloc[0]
    assert row.temp_lag1 == 119
    assert row.temp_clim == np.mean([120 - 52, 120 - 104])  # same week in the two earlier years
    year_two = at(f, week_of(60, 120)).iloc[0]
    assert year_two.temp_clim == 60 - 52  # only one earlier year exists
    assert np.isnan(at(f, week_of(10, 120)).iloc[0].temp_clim)


# --- the target week -------------------------------------------------------------------------------


def test_the_target_week_has_one_row_per_series_and_no_observations():
    panel = make_panel(n_weeks=70)
    target = week_of(70, 70)
    row = at(features_for(panel, target), target)
    assert len(row) == 4 * 2
    for column in ("lbs", "households", "demand_adj", "temp", "precip"):
        assert row[column].isna().all()


def test_calendar_flags_for_a_week_with_no_data_come_from_the_rules():
    panel = make_panel(n_weeks=70)
    target = week_of(70, 70)
    row = at(features_for(panel, target), target)
    for r in row.itertuples():
        assert bool(r.school_holiday) == school_holiday(r.county, target)
        assert bool(r.benefit_week) == benefit_week(r.county, target)


def test_calendar_flags_for_past_weeks_come_from_the_stored_data():
    panel = make_panel(pantries=(1,), categories=(1,), n_weeks=70)
    week = week_of(30, 70)
    panel.loc[panel.week_start == pd.Timestamp(week), "school_holiday"] = ~panel.loc[
        panel.week_start == pd.Timestamp(week), "school_holiday"
    ]
    row = at(features_for(panel, week_of(70, 70)), week).iloc[0]
    stored = panel.loc[panel.week_start == pd.Timestamp(week), "school_holiday"].iloc[0]
    assert bool(row.school_holiday) == bool(stored)


def test_the_forecast_week_must_come_after_the_data():
    panel = make_panel(n_weeks=70)
    with pytest.raises(ValueError, match="after"):
        fc.build_frame(panel, week_of(69, 70))


# --- no future data ----------------------------------------------------------------------------------


def test_features_are_identical_whether_or_not_later_weeks_exist():
    """Features for every week up to t are the same when only data before t is available."""
    panel = make_panel(n_weeks=N, shortages=[(2, 1, 90, 2, 30), (3, 2, 70, 3, 10)])
    cut = week_of(100, N)
    full = features_for(panel, week_of(N, N))
    partial = features_for(panel[panel.week_start < pd.Timestamp(cut)], cut)
    a = (
        full[full.week_start <= pd.Timestamp(cut)]
        .set_index(KEYS, drop=False)[fc.FEATURES]
        .sort_index()
    )
    b = partial.set_index(KEYS, drop=False)[fc.FEATURES].sort_index()
    pd.testing.assert_frame_equal(a, b)


def test_a_weeks_own_observations_never_appear_in_its_features():
    """Replace everything observed in week s with garbage: week s's features do not move."""
    panel = make_panel(n_weeks=N, shortages=[(1, 1, 95, 2, 30)])
    week = pd.Timestamp(week_of(95, N))
    garbage = panel.copy()
    garbage.loc[garbage.week_start == week, ["lbs", "households", "temp", "precip"]] = 1e9
    garbage.loc[garbage.week_start == week, ["severity", "turned_away"]] = [3, 1e9]
    clean = features_for(panel, week_of(N, N))
    dirty = features_for(garbage, week_of(N, N))
    cols = fc.FEATURES
    same = clean[clean.week_start == week].set_index(KEYS, drop=False)[cols].sort_index()
    still = dirty[dirty.week_start == week].set_index(KEYS, drop=False)[cols].sort_index()
    pd.testing.assert_frame_equal(same, still)
    # ... but the next week does see it (so the test would notice if the garbage did nothing)
    nxt = pd.Timestamp(week_of(96, N))
    assert not clean[clean.week_start == nxt][cols].equals(dirty[dirty.week_start == nxt][cols])


def test_no_raw_current_week_column_is_a_feature():
    assert CURRENT_WEEK_COLUMNS.isdisjoint(fc.FEATURES)
    assert len(set(fc.FEATURES)) == len(fc.FEATURES)


def test_every_feature_is_defined_for_target_weeks_without_data():
    """If a feature needed the target week's own data it would be empty here."""
    panel = make_panel(n_weeks=N)
    target = week_of(N, N)
    row = at(features_for(panel, target), target)
    always_known = [c for c in fc.FEATURES if c not in ("lag52", "temp_clim")]
    assert not row[always_known].isna().any().any()


# --- training rows --------------------------------------------------------------------------------


def test_training_rows_are_before_the_target_week_with_a_known_target():
    panel = make_panel(n_weeks=70)
    target = week_of(70, 70)
    rows = fc.training_rows(features_for(panel, target), target)
    assert rows.week_start.max() < pd.Timestamp(target)
    assert rows.demand_adj.notna().all() and rows.lag4.notna().all()
    assert len(rows) == (70 - 4) * 4 * 2  # the first four weeks have no lag4


def test_the_week_filter_alone_keeps_the_forecast_week_out_of_training():
    """The forecast week has no target anyway; this checks the week filter on its own by giving
    it one, so removing either guard would be noticed."""
    panel = make_panel(n_weeks=70)
    target = week_of(70, 70)
    features = features_for(panel, target)
    features.loc[features.week_start == pd.Timestamp(target), "demand_adj"] = 123.0
    rows = fc.training_rows(features, target)
    assert (rows.week_start < pd.Timestamp(target)).all()
    assert not (rows.demand_adj == 123.0).any()
