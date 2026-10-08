"""Weekly demand forecasts per pantry and food category.

One LightGBM model covers every pantry and category. It predicts next week's demand as three
quantiles (P10, P50, P90), and a seasonal-naive baseline (what was observed the same week last
year) is kept for comparison.

The one hard rule is **no future data**. The forecast for week t is made at the start of week t,
so it may use what is known then: everything observed in weeks before t, and the calendar (school
holidays and benefit weeks are scheduled in advance). It may not use anything observed in week t:
not its pounds, household visits, shortage reports or weather. `build_frame` enforces this by
construction: it is only ever handed weeks before t, plus one empty row per series for week t.
This module never imports the data generator or its true demand.

Censored demand
---------------
What a pantry hands out is capped by what it received. In a week when it ran short, the observed
pounds under-record what households needed; learning from them as-is would teach the model to
forecast scarcity instead of demand. For a pantry, category and week that has a shortage report,
the training target is raised:

    shortfall = min(0.5, max(prior[severity], households_turned_away / households_visiting))
    demand    = observed_lbs / (1 - shortfall)

with priors of 10%, 25% and 50% for severity 1, 2 and 3 ("minor", "serious", "ran out"). The
severity prior is the floor; if many households were turned away the larger share wins; nothing
claims more than half was unmet. Weeks without a report are left alone, so unreported shortages
remain a source of downward bias. The constants are assumptions, and the backtest report measures
what the correction is worth.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd

from app.services.calendar_rules import benefit_week, school_holiday
from app.storage import StorageBackend

logger = logging.getLogger("pantrypulse.forecast")

# --- censoring correction ---------------------------------------------------------------------

SEVERITY_SHORTFALL = {1: 0.10, 2: 0.25, 3: 0.50}
MAX_SHORTFALL = 0.50


def censoring_shortfall(severity, turned_away, households):
    """Share of true demand assumed unmet in a week with a shortage report (0 if none)."""
    sev = np.asarray(severity, dtype=float)
    turned = np.asarray(turned_away, dtype=float)
    visiting = np.asarray(households, dtype=float)
    prior = np.select(
        [sev == 1, sev == 2, sev == 3], [SEVERITY_SHORTFALL[i] for i in (1, 2, 3)], default=0.0
    )
    unmet = np.nan_to_num(turned, nan=0.0) / np.maximum(np.nan_to_num(visiting, nan=1.0), 1.0)
    shortfall = np.where(np.isnan(sev), 0.0, np.minimum(MAX_SHORTFALL, np.maximum(prior, unmet)))
    return float(shortfall) if shortfall.ndim == 0 else shortfall


def apply_censoring_correction(panel: pd.DataFrame, enabled: bool = True) -> pd.DataFrame:
    """Add `has_report`, `shortfall` and `demand_adj` (the training target)."""
    out = panel.copy()
    out["has_report"] = out["severity"].notna().astype(int)
    out["shortfall"] = censoring_shortfall(out["severity"], out["turned_away"], out["households"])
    out["demand_adj"] = out["lbs"] / (1 - out["shortfall"]) if enabled else out["lbs"]
    return out


# --- features -----------------------------------------------------------------------------------

LAGS = (1, 2, 3, 4, 52)
FEATURES = [
    "lag1", "lag2", "lag3", "lag4", "lag52", "rm4", "rm12",  # earlier demand
    "hh_lag1", "hh_rm4",  # earlier household visits
    "short_lag1", "short_cnt4", "shortfall_lag1",  # earlier shortages
    "temp_lag1", "precip_lag1", "temp_clim",  # earlier weather and the same week in earlier years
    "woy", "school_holiday", "benefit_week",  # the calendar, known in advance
    "baseline_households", "pantry_id", "category_id",  # who and what
]  # fmt: skip
CATEGORICAL = ["pantry_id", "category_id"]
# Raw columns describing the week being forecast. None of them may ever be a model input.
CURRENT_WEEK_COLUMNS = frozenset(
    {"lbs", "households", "severity", "turned_away", "temp", "precip", "demand_adj", "shortfall",
     "has_report", "baseline_lbs"}
)  # fmt: skip
KEY = ["pantry_id", "category_id"]
OBSERVED = ["lbs", "households", "severity", "turned_away", "temp", "precip", "school_holiday",
            "benefit_week", "has_report", "shortfall", "demand_adj"]  # fmt: skip


def build_frame(panel: pd.DataFrame, target_week, correction: bool = True) -> pd.DataFrame:
    """Every series for every week up to `target_week`, with the target week left empty.

    `panel` must contain only weeks before `target_week`. This is the leakage guard: the week
    being forecast has no observations here, so nothing downstream can read them.
    """
    target = pd.Timestamp(target_week)
    if panel.empty or panel["week_start"].max() >= target:
        raise ValueError("The forecast week must be after the last week of data it is given.")
    corrected = apply_censoring_correction(panel, correction)
    weeks = pd.date_range(corrected["week_start"].min(), target, freq="7D")
    series = corrected[KEY].drop_duplicates()
    grid = series.merge(pd.DataFrame({"week_start": weeks}), how="cross")
    frame = grid.merge(
        corrected[KEY + ["week_start"] + OBSERVED], on=KEY + ["week_start"], how="left"
    )
    static = corrected.groupby("pantry_id")[["county", "baseline_households"]].first().reset_index()
    frame = frame.merge(static, on="pantry_id", how="left")

    # Calendar flags: stored for past weeks, from the rules for weeks with no stored row.
    for column, rule in (("school_holiday", school_holiday), ("benefit_week", benefit_week)):
        missing = frame[column].isna()
        if missing.any():
            needed = frame.loc[missing, ["county", "week_start"]].drop_duplicates()
            lookup = {
                (c, w): rule(c, w.date())
                for c, w in zip(needed.county, needed.week_start, strict=True)
            }
            frame.loc[missing, column] = [
                lookup[(c, w)]
                for c, w in zip(
                    frame.loc[missing, "county"], frame.loc[missing, "week_start"], strict=True
                )
            ]
        frame[column] = frame[column].astype(int)
    return frame.sort_values(KEY + ["week_start"]).reset_index(drop=True)


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the model's features. Every one looks backwards (shifted by at least one week) or is
    calendar or static, so the row for week s only depends on weeks before s."""
    f = frame.copy()
    g = f.groupby(KEY, sort=False)
    for k in LAGS:
        f[f"lag{k}"] = g["demand_adj"].shift(k)
    keys = [f["pantry_id"], f["category_id"]]
    # Shift first, so a rolling window over this series never holds week s itself.
    demand_before = g["demand_adj"].shift(1)
    f["rm4"] = demand_before.groupby(keys).transform(lambda s: s.rolling(4, min_periods=4).mean())
    f["rm12"] = demand_before.groupby(keys).transform(
        lambda s: s.rolling(12, min_periods=12).mean()
    )
    f["hh_lag1"] = g["households"].shift(1)
    f["hh_rm4"] = f["hh_lag1"].groupby(keys).transform(lambda s: s.rolling(4, min_periods=2).mean())
    f["short_lag1"] = g["has_report"].shift(1)
    f["short_cnt4"] = (
        f["short_lag1"].groupby(keys).transform(lambda s: s.rolling(4, min_periods=1).sum())
    )
    f["shortfall_lag1"] = g["shortfall"].shift(1)
    f["temp_lag1"] = g["temp"].shift(1)
    f["precip_lag1"] = g["precip"].shift(1)
    # The same week in the two earlier years: an average of lags, so never the week itself.
    f["temp_clim"] = pd.concat([g["temp"].shift(52), g["temp"].shift(104)], axis=1).mean(axis=1)
    f["woy"] = f["week_start"].dt.isocalendar().week.astype(int)
    f["baseline_lbs"] = g["lbs"].shift(52)  # seasonal naive: observed pounds a year ago
    return f


def training_rows(features: pd.DataFrame, target_week) -> pd.DataFrame:
    """Rows the model may learn from: weeks before the target week with a known target."""
    target = pd.Timestamp(target_week)
    keep = (
        (features["week_start"] < target)
        & features["lag4"].notna()
        & features["demand_adj"].notna()
    )
    return features[keep]


# --- metrics --------------------------------------------------------------------------------------


def wape(actual, forecast) -> float:
    """Weighted absolute percentage error: total absolute error over total actual. Pairs with a
    missing value are ignored. NaN if there is nothing to score."""
    y = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    ok = np.isfinite(y) & np.isfinite(f)
    total = np.abs(y[ok]).sum()
    return float(np.abs(y[ok] - f[ok]).sum() / total) if total > 0 else float("nan")


def wape_by_series(df: pd.DataFrame, forecast_col: str, actual_col: str = "lbs") -> pd.Series:
    scored = df[[*KEY, actual_col, forecast_col]].dropna()
    scored = scored.assign(
        err=(scored[actual_col] - scored[forecast_col]).abs(), ay=scored[actual_col].abs()
    )
    sums = scored.groupby(KEY)[["err", "ay"]].sum()
    return (sums["err"] / sums["ay"].where(sums["ay"] > 0)).rename("wape")


def interval_coverage(actual, lower, upper) -> float:
    y, lo, hi = (np.asarray(x, dtype=float) for x in (actual, lower, upper))
    ok = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    return float(((y[ok] >= lo[ok]) & (y[ok] <= hi[ok])).mean()) if ok.any() else float("nan")


def share_below(series: pd.Series, threshold: float) -> float:
    values = series.dropna()
    return float((values < threshold).mean()) if len(values) else float("nan")


# --- the model ------------------------------------------------------------------------------------


class NotEnoughHistory(Exception):
    def __init__(self, found: int, needed: int):
        super().__init__(f"Need at least {needed} weeks of history to forecast; found {found}.")
        self.found, self.needed = found, needed


@dataclass(frozen=True)
class ForecastConfig:
    """Fixed up front. Nothing here is tuned on the backtest weeks."""

    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_data_in_leaf: int = 50
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    seed: int = 1
    num_threads: int = 4
    min_history_weeks: int = 56  # a year of lags plus a few weeks to learn from
    backtest_weeks: int = 12


QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}


@dataclass
class Models:
    boosters: dict[str, lgb.Booster]
    features: list[str]
    train_rows: int
    train_start: date
    train_end: date
    config: ForecastConfig = field(default_factory=ForecastConfig)


def _params(config: ForecastConfig, alpha: float) -> dict:
    return {
        "objective": "quantile",
        "alpha": alpha,
        "learning_rate": config.learning_rate,
        "num_leaves": config.num_leaves,
        "min_data_in_leaf": config.min_data_in_leaf,
        "feature_fraction": config.feature_fraction,
        "bagging_fraction": config.bagging_fraction,
        "bagging_freq": config.bagging_freq,
        "seed": config.seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": config.num_threads,
        "verbose": -1,
    }


def fit_models(
    train: pd.DataFrame, config: ForecastConfig, quantiles=("p10", "p50", "p90")
) -> Models:
    """Train one global model per quantile on log(1 + corrected demand). A monotone transform
    keeps quantiles intact, and it stops the biggest pantries from dominating the fit."""
    assert CURRENT_WEEK_COLUMNS.isdisjoint(FEATURES)
    x = train[FEATURES]
    y = np.log1p(train["demand_adj"].to_numpy())
    boosters = {}
    for name in quantiles:
        data = lgb.Dataset(x, y, categorical_feature=CATEGORICAL, free_raw_data=False)
        boosters[name] = lgb.train(_params(config, QUANTILES[name]), data, config.n_estimators)
    return Models(
        boosters=boosters,
        features=list(FEATURES),
        train_rows=len(train),
        train_start=train["week_start"].min().date(),
        train_end=train["week_start"].max().date(),
        config=config,
    )


def order_quantiles(predictions: pd.DataFrame) -> pd.DataFrame:
    """Quantile models are trained separately and can cross; make P10 <= P50 <= P90."""
    ordered = np.sort(predictions[["p10", "p50", "p90"]].to_numpy(), axis=1)
    return pd.DataFrame(ordered, columns=["p10", "p50", "p90"], index=predictions.index)


def predict(models: Models, rows: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=rows.index)
    for name, booster in models.boosters.items():
        out[name] = np.clip(np.expm1(booster.predict(rows[models.features])), 0, None)
    return order_quantiles(out) if {"p10", "p50", "p90"} <= set(out.columns) else out


def save_models(storage: StorageBackend, prefix: str, models: Models) -> None:
    for name, booster in models.boosters.items():
        storage.put(f"{prefix}/{name}.txt", booster.model_to_string().encode(), "text/plain")
    meta = {
        "features": models.features,
        "categorical": CATEGORICAL,
        "quantiles": list(models.boosters),
        "train_rows": models.train_rows,
        "train_start": models.train_start.isoformat(),
        "train_end": models.train_end.isoformat(),
        "config": models.config.__dict__,
    }
    storage.put(f"{prefix}/meta.json", json.dumps(meta, indent=2).encode(), "application/json")


def load_models(storage: StorageBackend, prefix: str) -> Models:
    meta = json.loads(storage.get(f"{prefix}/meta.json"))
    boosters = {
        name: lgb.Booster(model_str=storage.get(f"{prefix}/{name}.txt").decode())
        for name in meta["quantiles"]
    }
    return Models(
        boosters=boosters,
        features=meta["features"],
        train_rows=meta["train_rows"],
        train_start=date.fromisoformat(meta["train_start"]),
        train_end=date.fromisoformat(meta["train_end"]),
        config=ForecastConfig(**meta["config"]),
    )


# --- forecasting next week ------------------------------------------------------------------------

KEY_COLUMNS = ["pantry_id", "category_id", "week_start"]


@dataclass
class ForwardResult:
    week_start: date
    predictions: pd.DataFrame  # pantry_id, category_id, p10, p50, p90, baseline_lbs
    models: Models


def _check_history(panel: pd.DataFrame, needed: int) -> None:
    found = int(panel["week_start"].nunique()) if len(panel) else 0
    if found < needed:
        raise NotEnoughHistory(found, needed)


def forward_forecast(panel: pd.DataFrame, config: ForecastConfig) -> ForwardResult:
    """Train once on all history and forecast the week after the last one."""
    _check_history(panel, config.min_history_weeks)
    target = panel["week_start"].max() + pd.Timedelta(weeks=1)
    features = build_features(build_frame(panel, target))
    models = fit_models(training_rows(features, target), config)
    rows = features[features["week_start"] == target]
    predictions = pd.concat([rows[[*KEY, "baseline_lbs"]], predict(models, rows)], axis=1)
    return ForwardResult(target.date(), predictions.reset_index(drop=True), models)


# --- the backtest ---------------------------------------------------------------------------------


@dataclass
class FoldInfo:
    origin: date  # the week that was forecast
    train_rows: int
    train_end: date  # the last week the model learned from
    seconds: float


@dataclass
class BacktestResult:
    predictions: pd.DataFrame
    folds: list[FoldInfo]
    models: Models  # the last fold's, for saving
    config: ForecastConfig


def run_backtest(
    panel: pd.DataFrame,
    config: ForecastConfig,
    weeks: int | None = None,
    ablation: bool = True,
    progress: Callable[[FoldInfo], None] | None = None,
) -> BacktestResult:
    """Rolling origin: for each of the last `weeks` weeks, pretend it is the start of that week,
    train on everything before it, and forecast it. Each origin is refit from scratch on a panel
    that does not contain the week being forecast (or any later week).

    With `ablation`, a second model is trained the same way but with no censoring correction, so
    the report can show what the correction is worth.
    """
    weeks = config.backtest_weeks if weeks is None else weeks
    all_weeks = sorted(panel["week_start"].unique())
    first_origin_index = len(all_weeks) - weeks
    if first_origin_index < config.min_history_weeks:
        raise NotEnoughHistory(max(first_origin_index, 0), config.min_history_weeks)

    actual = panel[[*KEY_COLUMNS, "lbs", "severity"]].rename(columns={"severity": "_severity"})
    pieces, folds, last_models = [], [], None
    for origin in all_weeks[first_origin_index:]:
        started = time.perf_counter()
        history = panel[panel["week_start"] < origin]
        assert history["week_start"].max() < origin  # nothing from the forecast week onward
        features = build_features(build_frame(history, origin))
        train = training_rows(features, origin)
        assert train["week_start"].max() < origin
        models = fit_models(train, config)
        rows = features[features["week_start"] == origin]
        out = pd.concat([rows[[*KEY_COLUMNS, "baseline_lbs"]], predict(models, rows)], axis=1)

        if ablation:
            plain = build_features(build_frame(history, origin, correction=False))
            plain_models = fit_models(training_rows(plain, origin), config, quantiles=("p50",))
            plain_rows = plain[plain["week_start"] == origin]
            out["p50_uncorrected"] = predict(plain_models, plain_rows)["p50"].to_numpy()

        pieces.append(out)
        last_models = models
        info = FoldInfo(
            pd.Timestamp(origin).date(),
            len(train),
            train["week_start"].max().date(),
            time.perf_counter() - started,
        )
        folds.append(info)
        if progress:
            progress(info)

    predictions = pd.concat(pieces, ignore_index=True).merge(actual, on=KEY_COLUMNS, how="left")
    predictions["had_report"] = predictions.pop("_severity").notna()
    return BacktestResult(predictions, folds, last_models, config)


def summarize_backtest(predictions: pd.DataFrame) -> dict:
    """Headline numbers. Both models are scored on the same rows (those with a baseline)."""
    scored = predictions.dropna(subset=["lbs", "baseline_lbs"])
    by_series = wape_by_series(scored, "p50")
    baseline_by_series = wape_by_series(scored, "baseline_lbs")
    return {
        "rows_scored": len(scored),
        "wape_lightgbm": wape(scored["lbs"], scored["p50"]),
        "wape_baseline": wape(scored["lbs"], scored["baseline_lbs"]),
        "coverage_p10_p90": interval_coverage(scored["lbs"], scored["p10"], scored["p90"]),
        "series": int(by_series.notna().sum()),
        "median_series_wape_lightgbm": float(by_series.median()),
        "median_series_wape_baseline": float(baseline_by_series.median()),
        "share_series_under_20": share_below(by_series, 0.20),
        "share_series_under_20_baseline": share_below(baseline_by_series, 0.20),
    }
