"""Small, deterministic panels (the table `load_panel` returns) for the forecasting tests."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.constants import COUNTIES
from app.services.calendar_rules import benefit_week, school_holiday

LAST_WEEK = date(2026, 9, 28)  # the Monday of the last week with data
COUNTY_LIST = list(COUNTIES)


def week_of(index: int, n_weeks: int, last: date = LAST_WEEK) -> date:
    return last - timedelta(weeks=n_weeks - 1 - index)


def make_panel(
    pantries=(1, 2, 3, 4),
    categories=(1, 2),
    n_weeks=70,
    last: date = LAST_WEEK,
    lbs_fn=None,
    shortages=(),
    seed=0,
) -> pd.DataFrame:
    """One row per pantry, category and week.

    `lbs_fn(pantry, category, week_index)` sets the observed pounds (default: a seasonal pattern
    with a level per pantry). `shortages` is a list of (pantry, category, week_index, severity,
    households_turned_away) that become shortage reports on those rows.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for p in pantries:
        county = COUNTY_LIST[p % len(COUNTY_LIST)]
        for c in categories:
            for k in range(n_weeks):
                week = week_of(k, n_weeks, last)
                if lbs_fn:
                    lbs = float(lbs_fn(p, c, k))
                else:
                    season = 1 + 0.3 * np.sin(2 * np.pi * k / 52)
                    lbs = 500 * p * (1 + 0.2 * c) * season * (1 + rng.normal(0, 0.03))
                rows.append(
                    {
                        "pantry_id": p,
                        "category_id": c,
                        "week_start": pd.Timestamp(week),
                        "lbs": lbs,
                        "households": 100.0 * p + (k % 5),
                        "severity": np.nan,
                        "turned_away": np.nan,
                        "county": county,
                        "baseline_households": 400 * p,
                        "temp": 50 + 20 * np.sin(2 * np.pi * (k - 13) / 52) + p,
                        "precip": 0.5 + 0.1 * (k % 4),
                        "school_holiday": school_holiday(county, week),
                        "benefit_week": benefit_week(county, week),
                    }
                )
    panel = pd.DataFrame(rows)
    for p, c, k, severity, turned_away in shortages:
        mask = (
            (panel.pantry_id == p)
            & (panel.category_id == c)
            & (panel.week_start == pd.Timestamp(week_of(k, n_weeks, last)))
        )
        assert mask.sum() == 1, "shortage must point at an existing row"
        panel.loc[mask, ["severity", "turned_away"]] = [severity, turned_away]
    return panel
