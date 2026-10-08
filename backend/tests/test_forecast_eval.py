"""The backtest report: scoring against the true demand, the leakage probe and the document."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from app.services import forecasting as fc
from eval import forecast_backtest as bt
from scripts.generate_synthetic_data import FIRST_WEEK
from tests.forecast_fixtures import make_panel

FAST = fc.ForecastConfig(
    n_estimators=15, num_leaves=7, min_data_in_leaf=5, num_threads=2, min_history_weeks=30
)


def predictions_frame():
    weeks = [pd.Timestamp(FIRST_WEEK + timedelta(weeks=i)) for i in (10, 11)]
    rows = []
    for p in (1, 2):
        for w in weeks:
            rows.append({"pantry_id": p, "category_id": 1, "week_start": w, "lbs": 90.0,
                         "p10": 70.0, "p50": 100.0, "p90": 130.0, "baseline_lbs": 80.0,
                         "p50_uncorrected": 95.0, "had_report": p == 2})  # fmt: skip
    return pd.DataFrame(rows)


def truth_array(value=100.0):
    truth = np.full((85, 8, 156), value)
    truth[1, 0, 10] = 200.0  # pantry 2, category 1, week 10
    return truth


def test_truth_is_looked_up_by_pantry_category_and_week():
    looked_up = bt.truth_for(predictions_frame(), truth_array())
    assert looked_up.tolist() == [100.0, 100.0, 200.0, 100.0]


def test_scoring_against_the_truth_uses_the_same_rows_and_all_three_models():
    scores = bt.score_against_truth(predictions_frame(), truth_array())
    assert scores["wape_lightgbm"] == pytest.approx(fc.wape([100, 100, 200, 100], [100] * 4))
    assert scores["wape_baseline"] == pytest.approx(fc.wape([100, 100, 200, 100], [80] * 4))
    assert scores["wape_uncorrected"] == pytest.approx(fc.wape([100, 100, 200, 100], [95] * 4))
    assert scores["coverage_p10_p90"] == pytest.approx(3 / 4)  # 200 is outside [70, 130]


def test_the_database_is_recognised_as_coming_from_the_generator():
    from scripts.generate_synthetic_data import generate

    data = generate(515)
    panel = pd.DataFrame(data.distributions).rename(columns={"week_start": "week_start"})
    panel["week_start"] = pd.to_datetime(panel["week_start"])
    assert bt.database_matches_generator(panel, data)
    changed = panel.copy()
    changed.loc[changed.index[:50], "lbs"] += 5
    assert not bt.database_matches_generator(changed, data)
    assert not bt.database_matches_generator(panel.iloc[:-10], data)


def test_the_leakage_probe_finds_no_difference_on_a_clean_panel():
    probe = bt.leakage_probe(make_panel(n_weeks=80, shortages=[(1, 1, 50, 2, 20)]), weeks_back=3)
    assert probe["max_abs_difference"] == 0.0 and probe["features_compared"] > 0
    assert probe["rows_compared"] > 0


def test_the_leakage_probe_would_notice_a_feature_that_peeks(monkeypatch):
    """Sanity check of the probe itself: break the lag so it reads the same week."""
    real = fc.build_features

    def peeking(frame):
        out = real(frame)
        out["lag1"] = frame["demand_adj"]  # the week's own value: exactly the bug we guard against
        return out

    monkeypatch.setattr(fc, "build_features", peeking)
    probe = bt.leakage_probe(make_panel(n_weeks=80), weeks_back=3)
    assert probe["max_abs_difference"] > 0


def sample_result():
    panel = make_panel(n_weeks=70, shortages=[(1, 1, 60, 2, 20)])
    result = fc.run_backtest(panel, FAST, weeks=6)
    return panel, result


def test_the_report_has_every_section_and_the_headline_numbers():
    panel, result = sample_result()
    summary = fc.summarize_backtest(result.predictions)
    text = bt.render_report(
        result, summary, truth_scores=None, panel=panel, run_id=7, when="2026-10-08 12:00",
        seconds=12.3, probe=bt.leakage_probe(panel, 3), db_matches=True,
    )  # fmt: skip
    for heading in ("## Overall accuracy", "## Leakage checks", "## Method", "## By category",
                    "## Weeks with a shortage report", "## Each origin", "## Hardest series",
                    "## Assumptions and limits"):  # fmt: skip
        assert heading in text, heading
    assert f"{summary['wape_lightgbm']:.1%}" in text and f"{summary['wape_baseline']:.1%}" in text
    assert f"{summary['coverage_p10_p90']:.1%}" in text
    assert "run 7" in text.lower() or "Run 7" in text


def test_the_report_lists_every_leakage_check_with_how_it_is_verified():
    assert len(bt.LEAKAGE_CHECKS) >= 15
    for check in bt.LEAKAGE_CHECKS:
        assert check["rule"] and check["how"] and check["verified_by"]
    panel, result = sample_result()
    text = bt.render_report(
        result, fc.summarize_backtest(result.predictions), None, panel, 1, "now", 1.0,
        bt.leakage_probe(panel, 3), True,
    )  # fmt: skip
    assert text.count("| L") >= len(bt.LEAKAGE_CHECKS)


def test_every_test_the_report_cites_really_exists():
    import importlib
    import inspect
    from pathlib import Path

    tests_dir = Path(bt.__file__).resolve().parents[1] / "tests"
    available = {}
    for path in tests_dir.glob("test_*.py"):
        module = importlib.import_module(f"tests.{path.stem}")
        available[path.stem] = {
            n for n, f in inspect.getmembers(module, inspect.isfunction) if n.startswith("test_")
        }
    for check in bt.LEAKAGE_CHECKS:
        for ref in check["tests"]:
            module, _, name = ref.partition("::")
            assert name in available.get(module, set()), f"{ref} is cited but does not exist"


def test_the_truth_section_is_clearly_labelled_synthetic_only():
    panel, result = sample_result()
    scores = {"wape_lightgbm": 0.1, "wape_baseline": 0.2, "wape_uncorrected": 0.15,
              "coverage_p10_p90": 0.8}  # fmt: skip
    text = bt.render_report(
        result, fc.summarize_backtest(result.predictions), scores, panel, 1, "now", 1.0,
        bt.leakage_probe(panel, 3), True,
    )  # fmt: skip
    assert "true demand" in text.lower() and "never used" in text.lower() and "10.0%" in text
    without = bt.render_report(
        result, fc.summarize_backtest(result.predictions), None, panel, 1, "now", 1.0,
        bt.leakage_probe(panel, 3), False,
    )  # fmt: skip
    assert "not generated from the seed" in without.lower() or "skipped" in without.lower()


def test_the_report_says_in_words_whether_the_correction_helped():
    panel, result = sample_result()
    preds = result.predictions.assign(truth=result.predictions.lbs * 1.1)
    result = fc.BacktestResult(preds, result.folds, result.models, result.config)
    scores = {"wape_lightgbm": 0.100, "wape_baseline": 0.200, "wape_uncorrected": 0.1003,
              "coverage_p10_p90": 0.8}  # fmt: skip
    text = bt.render_report(
        result, fc.summarize_backtest(preds), scores, panel, 1, "now", 1.0,
        bt.leakage_probe(panel, 3), True,
    )  # fmt: skip
    assert "Does the censoring correction help?" in text and "no measurable difference" in text
    better = bt.render_report(
        result, fc.summarize_backtest(preds), {**scores, "wape_uncorrected": 0.12}, panel, 1,
        "now", 1.0, bt.leakage_probe(panel, 3), True,
    )  # fmt: skip
    assert "improves" in better
    worse = bt.render_report(
        result, fc.summarize_backtest(preds), {**scores, "wape_uncorrected": 0.08}, panel, 1,
        "now", 1.0, bt.leakage_probe(panel, 3), True,
    )  # fmt: skip
    assert "worse" in worse
