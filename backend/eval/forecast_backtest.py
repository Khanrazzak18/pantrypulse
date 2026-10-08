"""Rolling-origin backtest of the demand forecast, saved to the database and written up.

    python -m eval.forecast_backtest          # (make backtest) about a minute

For each of the last 12 weeks it pretends to be at the start of that week, trains on everything
before it and forecasts it, for LightGBM, for the same model without the censoring correction,
and for the seasonal-naive baseline. Results are scored against what was observed, and (because
the data is synthetic) also against the true demand the simulator used. The true demand is read
here, after the backtest, and nowhere else: it is never a training input.
"""

from __future__ import annotations

import argparse
import platform
import time
from datetime import datetime
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config import ROOT, get_settings
from app.constants import CATEGORY_NAMES
from app.db import make_engine
from app.services import forecast_runs
from app.services import forecasting as fc
from app.storage import LocalStorage
from scripts.generate_synthetic_data import DEFAULT_SEED, FIRST_WEEK, generate_with_truth

REPORT_PATH = ROOT / "docs/eval/forecast-backtest.md"
TARGET = 0.20

# Every way future information could reach a forecast, and what stops it. The report prints this
# table; a test checks that every test cited here exists.
LEAKAGE_CHECKS = [
    {"id": "L1", "rule": "The forecast for week t is made at the start of week t, so only data through week t-1 exists.",
     "how": "Each backtest origin is a Monday; the model is handed only earlier weeks.",
     "verified_by": "Assertions inside run_backtest on every fold (history and training rows end before the origin).",
     "tests": ["test_forecast_model::test_each_fold_trains_only_on_weeks_before_its_target_week"]},
    {"id": "L2", "rule": "The panel given to the feature builder contains no week from t onward.",
     "how": "build_frame refuses any panel whose last week is not before the forecast week.",
     "verified_by": "Unit test and the fold assertions.",
     "tests": ["test_forecast_features::test_the_forecast_week_must_come_after_the_data"]},
    {"id": "L3", "rule": "The week being forecast carries no observations (pounds, households, shortage report, weather).",
     "how": "The target week is an empty row per series, created after the history is fixed.",
     "verified_by": "Unit test: every observed column is empty for the target week.",
     "tests": ["test_forecast_features::test_the_target_week_has_one_row_per_series_and_no_observations"]},
    {"id": "L4", "rule": "Lag and rolling-mean features look strictly backwards.",
     "how": "Lags are shifts of 1 week or more; rolling windows are computed on the already-shifted series, so a window never holds the week itself.",
     "verified_by": "Exact values on a ramp series, and a test that replaces a week's own data with garbage and checks its features do not move.",
     "tests": ["test_forecast_features::test_lags_and_rolling_means_on_a_ramp", "test_forecast_features::test_a_weeks_own_observations_never_appear_in_its_features"]},
    {"id": "L5", "rule": "A missing week is a gap, never filled by shifting older values forward.",
     "how": "Every series is reindexed to a complete weekly grid before shifting.",
     "verified_by": "Unit test with a deleted week.",
     "tests": ["test_forecast_features::test_a_missing_week_leaves_a_gap_instead_of_shifting_older_values_forward"]},
    {"id": "L6", "rule": "The weather of the forecast week is not a feature (in practice only a weather forecast would exist).",
     "how": "Only last week's weather and a climatology made of the same week one and two years earlier (lags of 52 and 104 weeks) are used.",
     "verified_by": "Unit test of the values; the weather columns of the target week are empty.",
     "tests": ["test_forecast_features::test_weather_features_are_last_weeks_weather_and_the_climatology"]},
    {"id": "L7", "rule": "School-holiday and benefit-week flags of the forecast week are used. JUDGEMENT CALL for review: they are scheduled in advance, so they are knowable at forecast time.",
     "how": "Stored flags for past weeks; the calendar rules (app/services/calendar_rules.py) for weeks with no stored row.",
     "verified_by": "Unit tests for both sources.",
     "tests": ["test_forecast_features::test_calendar_flags_for_a_week_with_no_data_come_from_the_rules", "test_forecast_features::test_calendar_flags_for_past_weeks_come_from_the_stored_data"]},
    {"id": "L8", "rule": "Static features (pantry, category, baseline households) do not change over time.",
     "how": "Taken once per pantry from the pantries table. baseline_households is a constant in this data.",
     "verified_by": "Design (no time-varying source); listed so a reviewer can challenge it.",
     "tests": ["test_forecast_features::test_every_feature_is_defined_for_target_weeks_without_data"]},
    {"id": "L9", "rule": "No raw current-week column is a model input.",
     "how": "FEATURES is a fixed list; the training function asserts it is disjoint from the current-week columns.",
     "verified_by": "Unit test on the list, and an assertion in fit_models.",
     "tests": ["test_forecast_features::test_no_raw_current_week_column_is_a_feature"]},
    {"id": "L10", "rule": "The model learns only from weeks before the origin.",
     "how": "training_rows keeps weeks earlier than the target week; each fold asserts the latest training week is before the origin.",
     "verified_by": "Unit test and the per-fold assertion.",
     "tests": ["test_forecast_features::test_training_rows_are_before_the_target_week_with_a_known_target"]},
    {"id": "L11", "rule": "The training target for week s is built only from week s's own shortage report and household visits (both known by the end of week s, before any later origin).",
     "how": "The correction is a row-wise formula; nothing from other weeks enters it.",
     "verified_by": "Unit tests of the formula and of its scope.",
     "tests": ["test_forecast_censoring::test_the_correction_applies_to_shortage_weeks_only"]},
    {"id": "L12", "rule": "A shortage report cannot spread to other weeks, categories or pantries.",
     "how": "The correction is keyed on the exact (pantry, category, week) of the report.",
     "verified_by": "Unit test with neighbours.",
     "tests": ["test_forecast_censoring::test_a_report_in_another_week_or_category_does_not_leak_onto_its_neighbours"]},
    {"id": "L13", "rule": "Nothing learned at one origin is carried to the next.",
     "how": "Every origin builds its features and trains fresh models from scratch.",
     "verified_by": "Code structure of run_backtest; more training rows at each later origin.",
     "tests": ["test_forecast_model::test_each_fold_trains_only_on_weeks_before_its_target_week"]},
    {"id": "L14", "rule": "No tuning, early stopping or model selection on the backtest weeks.",
     "how": "All hyperparameters are fixed in ForecastConfig before the first run; training uses a fixed tree count and a fixed seed.",
     "verified_by": "The configuration is printed in this report; training is deterministic.",
     "tests": ["test_forecast_model::test_training_is_deterministic"]},
    {"id": "L15", "rule": "The seasonal-naive baseline reads only observations from 52 weeks earlier.",
     "how": "It is a 52-week shift of observed pounds (not corrected demand).",
     "verified_by": "Unit tests on a tiny fixture.",
     "tests": ["test_forecast_baseline::test_baseline_is_the_observed_value_52_weeks_earlier", "test_forecast_baseline::test_baseline_never_peeks_forward"]},
    {"id": "L16", "rule": "Actuals are attached only after predictions exist, and are used only for scoring.",
     "how": "run_backtest merges observed pounds onto the finished predictions.",
     "verified_by": "Unit test comparing every checked row with the panel.",
     "tests": ["test_forecast_model::test_actuals_and_baseline_in_the_backtest_come_from_the_panel"]},
    {"id": "L17", "rule": "The simulator's true demand is never a training input.",
     "how": "The forecasting module does not import the generator, nothing under app/ uses it, no training function takes a truth argument. Only this script reads it, after the backtest, to report a second WAPE.",
     "verified_by": "Static checks of imports and signatures.",
     "tests": ["test_forecast_leakage::test_the_forecasting_module_does_not_import_the_generator_or_its_truth", "test_forecast_leakage::test_nothing_in_the_app_package_uses_the_latent_demand", "test_forecast_leakage::test_no_training_or_prediction_function_accepts_a_truth_argument", "test_forecast_leakage::test_the_only_user_of_the_truth_is_the_evaluation_script"]},
    {"id": "L18", "rule": "Overwriting the future with garbage changes no earlier prediction.",
     "how": "The backtest is run twice, once with every week from week 64 onward replaced by 1e9 values; predictions for earlier origins must be identical.",
     "verified_by": "End-to-end test, plus the same probe on the real data in this run (below).",
     "tests": ["test_forecast_model::test_overwriting_the_future_with_garbage_changes_no_earlier_prediction", "test_forecast_features::test_features_are_identical_whether_or_not_later_weeks_exist"]},
    {"id": "L19", "rule": "No statistic computed from test rows enters training (no target encoding, scaling or imputation from the test weeks).",
     "how": "The only transform is log(1 + demand) on the training target, which has no parameters. Missing values are left to LightGBM.",
     "verified_by": "Design; listed so a reviewer can challenge it.",
     "tests": ["test_forecast_model::test_the_target_is_demand_not_a_leaked_copy_of_a_feature"]},
]  # fmt: skip


# --- scoring against the true demand ----------------------------------------------------------


def truth_for(predictions: pd.DataFrame, truth: np.ndarray) -> np.ndarray:
    """True demand for each prediction row (pantry and category ids are index + 1)."""
    week = ((predictions["week_start"] - pd.Timestamp(FIRST_WEEK)).dt.days // 7).to_numpy()
    return truth[
        predictions["pantry_id"].to_numpy() - 1, predictions["category_id"].to_numpy() - 1, week
    ]


def score_against_truth(predictions: pd.DataFrame, truth: np.ndarray) -> dict:
    t = truth_for(predictions, truth)
    return {
        "wape_lightgbm": fc.wape(t, predictions["p50"]),
        "wape_baseline": fc.wape(t, predictions["baseline_lbs"]),
        "wape_uncorrected": fc.wape(t, predictions["p50_uncorrected"]),
        "coverage_p10_p90": fc.interval_coverage(t, predictions["p10"], predictions["p90"]),
    }


def database_matches_generator(panel: pd.DataFrame, data) -> bool:
    """Is the database what the generator makes from its seed? Only then is the truth valid."""
    generated = pd.DataFrame(data.distributions)[["pantry_id", "category_id", "week_start", "lbs"]]
    generated["week_start"] = pd.to_datetime(generated["week_start"])
    if len(generated) != len(panel):
        return False
    merged = generated.merge(
        panel[["pantry_id", "category_id", "week_start", "lbs"]],
        on=["pantry_id", "category_id", "week_start"],
        suffixes=("_gen", "_db"),
    )
    return (
        len(merged) == len(panel)
        and float((merged["lbs_gen"] - merged["lbs_db"]).abs().max()) < 0.01
    )


def leakage_probe(panel: pd.DataFrame, weeks_back: int = 3) -> dict:
    """Do features for earlier weeks change when later weeks exist, even as garbage? They must not.

    Compares the features of every week up to `cut` built (a) from data before `cut` only and
    (b) from the whole panel in which weeks from `cut` onward were replaced with garbage."""
    last = panel["week_start"].max()
    cut = last - pd.Timedelta(weeks=weeks_back - 1)
    clean = fc.build_features(fc.build_frame(panel[panel["week_start"] < cut], cut))
    garbage = panel.copy()
    future = garbage["week_start"] >= cut
    garbage.loc[future, ["lbs", "households", "temp", "precip"]] = 1e9
    garbage.loc[future, ["severity", "turned_away"]] = [3, 1e9]
    dirty = fc.build_features(fc.build_frame(garbage, last + pd.Timedelta(weeks=1)))
    keys = ["pantry_id", "category_id", "week_start"]
    a = clean[clean["week_start"] <= cut].set_index(keys, drop=False)[fc.FEATURES].sort_index()
    b = dirty[dirty["week_start"] <= cut].set_index(keys, drop=False)[fc.FEATURES].sort_index()
    a, b = a.align(b, join="outer")
    both = a.notna().to_numpy() & b.notna().to_numpy()
    differ_nan = a.isna().to_numpy() != b.isna().to_numpy()
    diff = np.where(both, np.abs(a.to_numpy(dtype=float) - b.to_numpy(dtype=float)), 0.0)
    worst = float("inf") if differ_nan.any() else float(np.nanmax(diff)) if diff.size else 0.0
    return {"max_abs_difference": worst, "rows_compared": len(a), "features_compared": len(fc.FEATURES),
            "weeks_replaced": weeks_back}  # fmt: skip


# --- the report ---------------------------------------------------------------------------------


def _pct(value) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.1%}"


def render_report(
    result: fc.BacktestResult,
    summary: dict,
    truth_scores: dict | None,
    panel: pd.DataFrame,
    run_id: int,
    when: str,
    seconds: float,
    probe: dict,
    db_matches: bool,
) -> str:
    preds = result.predictions
    scored = preds.dropna(subset=["lbs", "baseline_lbs"])
    cfg = result.config
    has_truth = "truth" in preds.columns
    by_series = {
        "LightGBM": fc.wape_by_series(scored, "p50"),
        "Baseline": fc.wape_by_series(scored, "baseline_lbs"),
    }
    if "p50_uncorrected" in scored:
        by_series["LightGBM, no correction"] = fc.wape_by_series(scored, "p50_uncorrected")
    width = (scored["p90"] - scored["p10"]).sum() / scored["p50"].sum()
    weeks = result.folds[0].origin, result.folds[-1].origin

    L = [
        "# Demand forecast backtest",
        "",
        f"- Run {run_id} on {when}; {len(result.folds)} weekly origins, {weeks[0]} to {weeks[1]}; "
        f"{summary['rows_scored']:,} pantry-category-week forecasts over {summary['series']} series.",
        f"- LightGBM {lightgbm.__version__}, Python {platform.python_version()}; the backtest took {seconds:.0f} s.",
        f"- Target: WAPE under {TARGET:.0%} per pantry and category.",
        "",
        "## Overall accuracy",
        "",
        "WAPE is total absolute error divided by total actual pounds. **Observed** is what pantries "
        "actually handed out, which supply caps in shortage weeks, so it is what can be measured in real "
        "life. **True demand** is what the simulator generated before supply capped it; it exists only "
        "because the data is synthetic and was never used to train anything.",
        "",
        "| Model | WAPE vs observed | WAPE vs true demand | Series under 20% (observed) |",
        "| --- | --- | --- | --- |",
    ]
    truth_key = {
        "Baseline": "wape_baseline",
        "LightGBM": "wape_lightgbm",
        "LightGBM, no correction": "wape_uncorrected",
    }
    observed = {"Baseline": summary["wape_baseline"], "LightGBM": summary["wape_lightgbm"],
                "LightGBM, no correction": fc.wape(scored["lbs"], scored["p50_uncorrected"]) if "p50_uncorrected" in scored else None}  # fmt: skip
    for name in ("Baseline", "LightGBM", "LightGBM, no correction"):
        if name not in by_series:
            continue
        t = truth_scores[truth_key[name]] if truth_scores else None
        L.append(
            f"| {name} | {_pct(observed[name])} | {_pct(t)} | {_pct(fc.share_below(by_series[name], TARGET))} |"
        )
    verdict = "meets" if summary["wape_lightgbm"] < TARGET else "does not meet"
    L += [
        "",
        f"LightGBM {verdict} the {TARGET:.0%} target overall against observed pounds "
        f"({_pct(summary['wape_lightgbm'])}, versus {_pct(summary['wape_baseline'])} for the baseline). "
        f"The median series has a WAPE of {_pct(summary['median_series_wape_lightgbm'])} "
        f"(baseline {_pct(summary['median_series_wape_baseline'])}); "
        f"{_pct(summary['share_series_under_20'])} of series are under {TARGET:.0%} "
        f"(baseline {_pct(summary['share_series_under_20_baseline'])}).",
        "",
    ]
    L += ["### Prediction interval (P10 to P90)", "", "| Measure | Value |", "| --- | --- |",
          f"| Coverage of observed pounds (ideal: 80%) | {_pct(summary['coverage_p10_p90'])} |"]  # fmt: skip
    if truth_scores:
        L.append(f"| Coverage of true demand | {_pct(truth_scores['coverage_p10_p90'])} |")
    L += [f"| Average interval width (P90 - P10, as a share of P50) | {_pct(width)} |", ""]

    if truth_scores:
        gap = truth_scores["wape_uncorrected"] - truth_scores["wape_lightgbm"]
        if abs(gap) < 0.005:
            verdict = "no measurable difference"
        elif gap > 0:
            verdict = f"the correction improves accuracy by {gap * 100:.1f} points"
        else:
            verdict = f"the correction makes it worse by {-gap * 100:.1f} points"
        in_shortage = ""
        if has_truth and "p50_uncorrected" in scored:
            part = scored[scored["had_report"]]
            if len(part):
                in_shortage = (
                    f" In the {len(part):,} forecasts for weeks with a shortage report, the corrected "
                    f"model scores {_pct(fc.wape(part['truth'], part['p50']))} against true demand and "
                    f"the uncorrected one {_pct(fc.wape(part['truth'], part['p50_uncorrected']))}."
                )
        L += [
            "### Does the censoring correction help?",
            "",
            f"Against true demand the corrected model scores {_pct(truth_scores['wape_lightgbm'])} and "
            f"the same model trained on raw observed pounds scores "
            f"{_pct(truth_scores['wape_uncorrected'])}: {verdict}.{in_shortage} Shortage reports cover "
            f"only {_pct(scored['had_report'].mean())} of forecasts, so even a large uplift on those "
            "rows moves the overall figure little.",
            "",
        ]
        L += [
            "### Reading the two columns",
            "",
            "Observed pounds are capped by supply, so a model that forecasts true demand is judged "
            "against a smaller number in shortage weeks and looks worse against observed than against "
            "true demand. The 'no correction' row shows what the censoring correction is worth: it is "
            "the same model trained on raw observed pounds. Its WAPE against true demand is the fair "
            "comparison.",
            "",
        ]
    else:
        L += [
            "The comparison with the true demand was skipped: the database is not generated from the "
            "seed (or the generator could not be matched to it), so the simulator's truth does not "
            "apply to it.",
            "",
        ]

    # --- leakage ---
    L += ["## Leakage checks", "",
          "A forecast for week t may only use what is known at the start of week t. Each row is one way "
          "future information could get in, how it is prevented, and the evidence. Tests are in `backend/tests/`.", "",
          "| # | Rule | How it is enforced | Evidence |", "| --- | --- | --- | --- |"]  # fmt: skip
    for c in LEAKAGE_CHECKS:
        tests = "; ".join(f"`{t}`" for t in c["tests"])
        L.append(f"| {c['id']} | {c['rule']} | {c['how']} | {c['verified_by']} {tests} |")
    verdict = (
        "no difference"
        if probe["max_abs_difference"] == 0
        else f"a difference of {probe['max_abs_difference']:g}"
    )
    L += ["", f"**Probe on this run's real data:** the last {probe['weeks_replaced']} weeks of the database were "
          f"replaced with garbage values (1e9 pounds, households and weather; a severity-3 shortage with 1e9 "
          f"households turned away), and the features of every earlier week ({probe['rows_compared']:,} rows x "
          f"{probe['features_compared']} features) were compared with features built from the untouched earlier "
          f"data alone: **{verdict}**.", "",
          "**Runtime assertions:** every one of the "
          f"{len(result.folds)} folds asserted that the history it was given and its training rows end before its "
          "origin, and that no current-week column is a feature; the run would have stopped otherwise.", ""]  # fmt: skip

    L += ["## Method", "",
          "- **Target:** weekly demand in pounds per pantry and category, predicted one week ahead. Trained on "
          "`log(1 + demand)`, with P10, P50 and P90 as separate LightGBM quantile models (P50 is the median, "
          "which is what WAPE rewards). Predictions are un-logged, clipped at 0 and sorted so P10 <= P50 <= P90.",
          "- **Censored demand:** when a pantry ran short of a category in a week and filed a report, the "
          "training target is `observed / (1 - shortfall)`, with `shortfall = min(0.5, max(prior[severity], "
          "households turned away / households visiting))` and priors of 10%, 25% and 50% for severity 1, 2, 3. "
          "Weeks without a report are left as observed. The constants are assumptions.",
          "- **Features:** " + ", ".join(f"`{f}`" for f in fc.FEATURES) + ".",
          "- **Baseline:** the pounds observed in the same week 52 weeks earlier.",
          "- **Backtest:** rolling origin over the last "
          f"{len(result.folds)} weeks. Each origin refits from scratch on all earlier weeks "
          f"({result.folds[0].train_rows:,} to {result.folds[-1].train_rows:,} training rows).",
          f"- **Fixed settings:** {cfg.n_estimators} trees, learning rate {cfg.learning_rate}, {cfg.num_leaves} leaves, "
          f"min {cfg.min_data_in_leaf} rows per leaf, feature fraction {cfg.feature_fraction}, bagging "
          f"{cfg.bagging_fraction}, seed {cfg.seed}. Chosen before any backtest and not tuned on these weeks.", ""]  # fmt: skip

    def table(frame: pd.DataFrame, group: pd.Series, labels, title: str) -> list[str]:
        rows = [f"## {title}", ""]
        head = "| Group | Forecasts | LightGBM | Baseline | No correction |" + (
            " LightGBM vs true | No correction vs true |" if has_truth else ""
        )
        rows += [head, "| --- | --- | --- | --- | --- |" + (" --- | --- |" if has_truth else "")]
        for key in labels:
            part = frame[group == key]
            if part.empty:
                continue
            line = (f"| {labels[key] if isinstance(labels, dict) else key} | {len(part):,} | {_pct(fc.wape(part['lbs'], part['p50']))} | "
                    f"{_pct(fc.wape(part['lbs'], part['baseline_lbs']))} | "
                    f"{_pct(fc.wape(part['lbs'], part['p50_uncorrected'])) if 'p50_uncorrected' in part else 'n/a'} |")  # fmt: skip
            if has_truth:
                line += f" {_pct(fc.wape(part['truth'], part['p50']))} | {_pct(fc.wape(part['truth'], part['p50_uncorrected'])) if 'p50_uncorrected' in part else 'n/a'} |"
            rows.append(line)
        return rows + [""]

    names = {i + 1: n for i, n in enumerate(CATEGORY_NAMES)}
    L += table(scored, scored["category_id"], names, "By category")
    L += table(scored, scored["had_report"].map({True: "reported a shortage", False: "no shortage report"}),
               {"reported a shortage": "Weeks with a shortage report", "no shortage report": "Weeks without one"},
               "Weeks with a shortage report vs without")  # fmt: skip

    L += ["## Each origin", "", "| Week forecast | Training rows | Trained through | LightGBM | Baseline | Coverage | Seconds |",
          "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for fold in result.folds:
        part = scored[scored["week_start"] == pd.Timestamp(fold.origin)]
        L.append(f"| {fold.origin} | {fold.train_rows:,} | {fold.train_end} | {_pct(fc.wape(part['lbs'], part['p50']))} | "
                 f"{_pct(fc.wape(part['lbs'], part['baseline_lbs']))} | "
                 f"{_pct(fc.interval_coverage(part['lbs'], part['p10'], part['p90']))} | {fold.seconds:.1f} |")  # fmt: skip

    worst = by_series["LightGBM"].sort_values(ascending=False).head(10)
    means = scored.groupby(["pantry_id", "category_id"])["lbs"].mean()
    L += [
        "",
        "## Hardest series",
        "",
        "| Pantry | Category | Average weekly lb | LightGBM | Baseline |",
        "| --- | --- | --- | --- | --- |",
    ]
    for (p, c), value in worst.items():
        L.append(
            f"| {p} | {names[c]} | {means[(p, c)]:,.0f} | {_pct(value)} | {_pct(by_series['Baseline'].get((p, c)))} |"
        )

    L += ["", "## Assumptions and limits", "",
          "- The data is synthetic. Its demand follows seasonality, school holidays, benefit weeks, weather and "
          "noise that the model's features describe, so accuracy here is likely better than on real manifests.",
          "- The shortage correction uses assumed constants. Only reported shortages are corrected (pantries "
          "report some of the weeks they run short), so some demand stays under-recorded.",
          "- Only 12 weekly origins are scored, with one data seed; 12 weeks is too few to say anything about "
          "seasonality in the errors.",
          "- WAPE for a single pantry and category rests on 12 numbers and can be dominated by one week.",
          "- The forecast uses last week's weather and a climatology, not the weather of the week being forecast; a real "
          "weather forecast could be added as a feature.",
          "- School-holiday and benefit-week flags are known schedules (check L7).",
          f"- Database matches the generator seed: {'yes' if db_matches else 'no (true-demand scoring skipped)'}.", "",
          "## Reproduce", "", "```", "make backtest", "```", ""]  # fmt: skip
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weeks", type=int, default=12)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    settings = get_settings()
    config = fc.ForecastConfig(backtest_weeks=args.weeks)
    engine = make_engine(settings.database_url)
    storage = LocalStorage(settings.storage_path)
    try:
        with Session(engine) as db:
            panel = forecast_runs.load_panel(db)
            print(
                f"{len(panel):,} rows, {panel['week_start'].nunique()} weeks; backtesting the last {args.weeks} weeks ..."
            )
            started = time.perf_counter()
            result = fc.run_backtest(
                panel, config, args.weeks,
                progress=lambda f: print(f"  forecast week {f.origin}: trained on {f.train_rows:,} rows ({f.seconds:.1f}s)"),
            )  # fmt: skip
            seconds = time.perf_counter() - started
            run = forecast_runs.save_backtest(db, storage, result, panel)
            print(f"saved backtest run {run.id} ({len(result.predictions):,} forecasts)")

            probe = leakage_probe(panel)
            data, truth = generate_with_truth(DEFAULT_SEED)
            matches = database_matches_generator(panel, data)
            truth_scores = None
            if matches:
                result.predictions["truth"] = truth_for(result.predictions, truth)
                truth_scores = score_against_truth(result.predictions, truth)
            summary = fc.summarize_backtest(result.predictions)
            when = datetime.now().strftime("%Y-%m-%d %H:%M")
            text = render_report(
                result, summary, truth_scores, panel, run.id, when, seconds, probe, matches
            )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text)
    finally:
        engine.dispose()

    print(f"\nReport written to {args.report}")
    print(
        f"WAPE vs observed:  LightGBM {summary['wape_lightgbm']:.1%}   baseline {summary['wape_baseline']:.1%}"
    )
    if truth_scores:
        print(
            f"WAPE vs true demand: LightGBM {truth_scores['wape_lightgbm']:.1%}   baseline "
            f"{truth_scores['wape_baseline']:.1%}   no correction {truth_scores['wape_uncorrected']:.1%}"
        )
    print(
        f"P10-P90 coverage: {summary['coverage_p10_p90']:.1%}   series under 20%: {summary['share_series_under_20']:.1%}"
    )


if __name__ == "__main__":
    main()
