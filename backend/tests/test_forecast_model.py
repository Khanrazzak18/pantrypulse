"""Training, prediction, saving and the rolling-origin backtest (small data, small trees)."""

import json

import numpy as np
import pandas as pd
import pytest

from app.services import forecasting as fc
from tests.forecast_fixtures import make_panel, week_of

FAST = fc.ForecastConfig(
    n_estimators=20, num_leaves=7, min_data_in_leaf=5, num_threads=2, min_history_weeks=30
)
N = 70


def fitted(panel=None, config=FAST):
    panel = make_panel(n_weeks=N) if panel is None else panel
    target = week_of(N, N)
    feats = fc.build_features(fc.build_frame(panel, target))
    train = fc.training_rows(feats, target)
    models = fc.fit_models(train, config)
    rows = feats[feats.week_start == pd.Timestamp(target)]
    return models, rows, train


# --- model ------------------------------------------------------------------------------------------


def test_predictions_are_ordered_and_never_negative():
    models, rows, _ = fitted()
    out = fc.predict(models, rows)
    assert list(out.columns) == ["p10", "p50", "p90"] and len(out) == 4 * 2
    assert (out.p10 <= out.p50).all() and (out.p50 <= out.p90).all() and (out >= 0).all().all()


def test_ordering_is_enforced_even_if_the_quantile_models_cross():
    out = fc.order_quantiles(
        pd.DataFrame({"p10": [5.0, 1.0], "p50": [3.0, 2.0], "p90": [4.0, 0.5]})
    )
    assert (out.p10 <= out.p50).all() and (out.p50 <= out.p90).all()
    assert out.iloc[0].tolist() == [3.0, 4.0, 5.0]


def test_training_is_deterministic():
    models_a, rows, _ = fitted()
    models_b, _, _ = fitted()
    pd.testing.assert_frame_equal(fc.predict(models_a, rows), fc.predict(models_b, rows))


def test_the_model_reports_what_it_was_trained_on():
    models, _, train = fitted()
    assert models.train_rows == len(train)
    assert models.train_end == pd.Timestamp(week_of(N - 1, N)).date()
    assert models.features == fc.FEATURES


def test_the_target_is_demand_not_a_leaked_copy_of_a_feature():
    panel = make_panel(n_weeks=N, lbs_fn=lambda p, c, k: 100.0 * p)
    # more converged than FAST: the small test config has not finished learning in 20 trees
    converged = fc.ForecastConfig(
        n_estimators=150, learning_rate=0.1, num_leaves=7, min_data_in_leaf=5, num_threads=2
    )
    models, rows, _ = fitted(panel, converged)
    out = fc.predict(models, rows)
    # a flat series per pantry: the median forecast should land close to the level
    expected = rows.pantry_id.to_numpy() * 100.0
    assert np.allclose(out.p50.to_numpy(), expected, rtol=0.15)


def test_models_survive_a_round_trip_through_storage(storage):
    models, rows, _ = fitted()
    fc.save_models(storage, "forecasts/run-7", models)
    for name in ("p10.txt", "p50.txt", "p90.txt", "meta.json"):
        assert storage.exists(f"forecasts/run-7/{name}")
    meta = json.loads(storage.get("forecasts/run-7/meta.json"))
    assert meta["features"] == fc.FEATURES and meta["train_rows"] == models.train_rows
    loaded = fc.load_models(storage, "forecasts/run-7")
    pd.testing.assert_frame_equal(fc.predict(models, rows), fc.predict(loaded, rows))


# --- the forward forecast -----------------------------------------------------------------------------


def test_the_forward_forecast_trains_once_and_predicts_the_week_after_the_data():
    result = fc.forward_forecast(make_panel(n_weeks=N), FAST)
    assert result.week_start == week_of(N, N)  # the Monday after the last week of data
    assert len(result.predictions) == 4 * 2
    assert result.models.train_end == week_of(N - 1, N)
    assert {"pantry_id", "category_id", "p10", "p50", "p90", "baseline_lbs"} <= set(
        result.predictions.columns
    )


def test_the_forward_forecast_refuses_too_little_history():
    with pytest.raises(fc.NotEnoughHistory) as exc:
        fc.forward_forecast(make_panel(n_weeks=20), FAST)
    assert exc.value.found == 20 and exc.value.needed == 30


# --- the backtest -------------------------------------------------------------------------------------


def backtest(panel=None, **kwargs):
    return fc.run_backtest(make_panel(n_weeks=N) if panel is None else panel, FAST, **kwargs)


def test_the_backtest_scores_the_last_12_weeks_one_origin_at_a_time():
    result = backtest()
    expected_weeks = [pd.Timestamp(week_of(k, N)).date() for k in range(N - 12, N)]
    assert [f.origin for f in result.folds] == expected_weeks
    assert len(result.predictions) == 12 * 4 * 2
    assert sorted(result.predictions.week_start.dt.date.unique()) == expected_weeks


def test_each_fold_trains_only_on_weeks_before_its_target_week():
    result = backtest()
    for fold in result.folds:
        assert fold.train_end < fold.origin
        assert (
            fold.origin - fold.train_end
        ).days == 7  # it uses everything up to last week, no gap
    rows = [f.train_rows for f in result.folds]
    assert rows == sorted(rows) and len(set(rows)) == 12  # more history at every later origin


def test_actuals_and_baseline_in_the_backtest_come_from_the_panel():
    panel = make_panel(n_weeks=N)
    result = backtest(panel)
    indexed = panel.set_index(["pantry_id", "category_id", "week_start"]).lbs
    p = result.predictions
    for row in p.sample(10, random_state=1).itertuples():
        key = (row.pantry_id, row.category_id, row.week_start)
        assert row.lbs == indexed[key]
        last_year = (row.pantry_id, row.category_id, row.week_start - pd.Timedelta(weeks=52))
        assert row.baseline_lbs == indexed[last_year]


def test_overwriting_the_future_with_garbage_changes_no_earlier_prediction():
    """The strongest leakage check: fold k must not depend on anything from week k onward."""
    clean = make_panel(n_weeks=N, shortages=[(2, 1, 50, 2, 30)])
    dirty = clean.copy()
    first_garbage = pd.Timestamp(week_of(64, N))
    late = dirty.week_start >= first_garbage
    dirty.loc[late, ["lbs", "households", "temp", "precip"]] = 1e9
    dirty.loc[late, ["severity", "turned_away"]] = [3, 1e9]
    a = backtest(clean).predictions
    b = backtest(dirty).predictions
    unaffected = a.week_start <= first_garbage  # origins up to week 64 only see weeks before 64
    cols = ["p10", "p50", "p90", "p50_uncorrected"]
    pd.testing.assert_frame_equal(
        a[unaffected].reset_index(drop=True)[cols], b[unaffected].reset_index(drop=True)[cols]
    )
    assert (
        not a[~unaffected]
        .reset_index(drop=True)[cols]
        .equals(b[~unaffected].reset_index(drop=True)[cols])
    )


def test_the_uncorrected_variant_differs_only_when_there_are_shortage_reports():
    with_reports = backtest(make_panel(n_weeks=N, shortages=[(1, 1, 40, 3, 80), (2, 2, 55, 2, 20)]))
    assert not np.allclose(with_reports.predictions.p50, with_reports.predictions.p50_uncorrected)
    without = backtest(make_panel(n_weeks=N))
    assert np.allclose(without.predictions.p50, without.predictions.p50_uncorrected)


def test_the_uncorrected_variant_can_be_skipped():
    assert "p50_uncorrected" not in backtest(ablation=False).predictions.columns


def test_backtest_needs_enough_history_for_the_weeks_it_scores():
    with pytest.raises(fc.NotEnoughHistory):
        fc.run_backtest(make_panel(n_weeks=35), FAST)  # 35 weeks - 12 scored leaves 23 < 30


def test_the_summary_reports_overall_series_and_coverage_numbers():
    result = backtest()
    s = fc.summarize_backtest(result.predictions)
    p = result.predictions
    assert s["wape_lightgbm"] == pytest.approx(fc.wape(p.lbs, p.p50))
    assert s["wape_baseline"] == pytest.approx(fc.wape(p.lbs, p.baseline_lbs))
    assert s["coverage_p10_p90"] == pytest.approx(fc.interval_coverage(p.lbs, p.p10, p.p90))
    assert s["series"] == 4 * 2 and 0 <= s["share_series_under_20"] <= 1
