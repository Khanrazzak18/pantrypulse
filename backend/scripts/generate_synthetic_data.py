"""Synthetic history for Harvest Bridge Food Bank: 85 pantries, 6 counties, 8 categories, 3 years.

A pure function of the seed: `generate(seed)` returns the same rows every time. Weather and
school holidays are synthetic too (they are not real county data).

How the history is produced, in order:
  1. Latent weekly demand per pantry and category: household count x pounds per household x
     seasonality, school holidays, benefit-payment weeks, weather and noise.
  2. Warehouse supply per category and week, received as lots. Perishable lots lose part of their
     weight to expiry (the spoilage the project is trying to cut).
  3. A rough, inconsistent manual allocation of what survives (the current process). A pantry
     receives min(demand, allocation), so recorded distributions are censored by supply.
  4. Pantries that received well under their demand sometimes file a shortage report.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np

from app.constants import CATEGORY_NAMES, COUNTIES, PERISHABLE_CATEGORIES
from app.services.calendar_rules import COUNTY_NAMES, benefit_week, school_holiday

DEFAULT_SEED = 515
N_PANTRIES = 85
N_WEEKS = 156
LAST_WEEK = date(2026, 9, 28)  # fixed, so output never depends on today's date
FIRST_WEEK = LAST_WEEK - timedelta(weeks=N_WEEKS - 1)

PANTRIES_PER_COUNTY = [18, 16, 15, 14, 12, 10]
TOTAL_HOUSEHOLDS_PER_MONTH = 40_000
WEEKS_PER_MONTH = 4.33
LBS_PER_HOUSEHOLD = 35.0

C = len(CATEGORY_NAMES)
CAT_INDEX = {name: i for i, name in enumerate(CATEGORY_NAMES)}
# share of a household's pounds by category: produce dairy protein bakery frozen canned dry bev
SHARE = np.array([0.22, 0.10, 0.14, 0.06, 0.04, 0.18, 0.20, 0.06])
PERISHABLE = np.array([name in PERISHABLE_CATEGORIES for name in CATEGORY_NAMES])

# --- tuning knobs (calibrated against the targets in CLAUDE.md; see the tests) --------------
# Mean ratio of usable weekly supply to total demand. Produce and protein are tightest, so they
# run short most often; surplus in the other categories is assumed to go to other agencies.
SUPPLY_RATIO = np.array([1.06, 1.20, 1.05, 1.24, 1.24, 1.26, 1.26, 1.24])
SUPPLY_NOISE = 0.07  # week-to-week donation variability, shared by all pantries
ALLOCATION_NOISE = 0.15  # how far the manual allocation drifts from true demand
SHORTAGE_THRESHOLD = 0.90  # received < 90% of demand counts as running short
REPORT_PROBABILITY = 0.60  # chance a short pantry files a report
REPORT_BY_CATEGORY = np.array([1.0, 0.6, 1.0, 0.45, 0.4, 0.3, 0.3, 0.4])
# Fraction of a short-lived perishable lot lost to expiry, by category.
SPOILAGE = np.array([0.145, 0.105, 0.118, 0.158, 0.01, 0.01, 0.01, 0.01])
LONG_LIFE_SPOILAGE = 0.01


ITEM_NAMES = {
    "produce": [
        "Romaine lettuce",
        "Russet potatoes",
        "Gala apples",
        "Carrots",
        "Yellow onions",
        "Cabbage",
    ],
    "dairy": [
        "2% milk",
        "Cheddar cheese",
        "Greek yogurt",
        "Large eggs",
        "Butter",
        "Cottage cheese",
    ],
    "protein": [
        "Chicken thighs",
        "Ground beef",
        "Pork loin",
        "Turkey breast",
        "Canned tuna case",
        "Dried lentils",
    ],
    "bakery": [
        "Whole wheat bread",
        "Dinner rolls",
        "Bagels",
        "Tortillas",
        "Sandwich buns",
        "Day-old pastries",
    ],
    "frozen": [
        "Frozen meals",
        "Frozen pizza",
        "Frozen waffles",
        "Ice pops",
        "Frozen burritos",
        "Pot pies",
    ],
    "canned": [
        "Canned green beans",
        "Canned corn",
        "Tomato soup",
        "Canned peaches",
        "Black beans",
        "Chili",
    ],
    "dry_goods": [
        "Long-grain rice",
        "Spaghetti",
        "Rolled oats",
        "Peanut butter",
        "Cereal",
        "Flour",
    ],
    "beverages": [
        "Bottled water",
        "Apple juice",
        "Shelf-stable milk",
        "Sports drink",
        "Orange juice",
        "Tea bags",
    ],
}
# (unit, pounds per unit)
UNITS = {
    "produce": ("case", 30.0), "dairy": ("case", 24.0), "protein": ("case", 40.0),
    "bakery": ("box", 18.0), "frozen": ("case", 30.0), "canned": ("case", 28.0),
    "dry_goods": ("case", 30.0), "beverages": ("case", 26.0),
}  # fmt: skip

DONORS = [
    ("Greenfield Market", "grocery"),
    ("Harbor Foods", "grocery"),
    ("Value Basket", "grocery"),
    ("Oakline Grocers", "grocery"),
    ("Sunrise Supermarket", "grocery"),
    ("Cornerstone Co-op", "grocery"),
    ("Millbrook Farm", "farm"),
    ("Three Rivers Orchard", "farm"),
    ("Stoneridge Dairy", "farm"),
    ("Hollow Creek Produce", "farm"),
    ("Prairie Gold Eggs", "farm"),
    ("Windmill Acres", "farm"),
    ("Ashford Elementary Drive", "food_drive"),
    ("St. Mark's Church Drive", "food_drive"),
    ("Rotary Club Drive", "food_drive"),
    ("Dunmore High Canned Goods Drive", "food_drive"),
    ("Elmhurst Library Drive", "food_drive"),
    ("Fairhaven Scouts Drive", "food_drive"),
    ("Metro Wholesale Foods", "other"),
    ("Daily Bread Bakery", "other"),
    ("Coldchain Distributors", "other"),
    ("Lakeside Restaurant Group", "other"),
]
# How likely each donor type is to supply each category (same order as CATEGORY_NAMES).
DONOR_AFFINITY = {
    "grocery": [3, 3, 3, 3, 3, 2, 2, 2],
    "farm": [5, 4, 2, 0, 0, 0, 0, 0],
    "food_drive": [0, 0, 0, 0, 0, 5, 5, 3],
    "other": [1, 1, 2, 4, 3, 1, 2, 2],
}


@dataclass
class SyntheticData:
    pantries: list[dict] = field(default_factory=list)
    weekly_context: list[dict] = field(default_factory=list)
    donors: list[dict] = field(default_factory=list)
    donations: list[dict] = field(default_factory=list)
    donation_items: list[dict] = field(default_factory=list)
    inventory_lots: list[dict] = field(default_factory=list)
    distributions: list[dict] = field(default_factory=list)
    shortage_reports: list[dict] = field(default_factory=list)
    # Stock on hand at the start of the forecast week. Not part of the 3-year history (and so not
    # in `tables()` or the fingerprint); `add_current_inventory` fills these in.
    current_donations: list[dict] = field(default_factory=list)
    current_donation_items: list[dict] = field(default_factory=list)
    current_lots: list[dict] = field(default_factory=list)

    def tables(self) -> dict[str, list[dict]]:
        """Tables in foreign-key order, ready to insert."""
        return {
            "pantries": self.pantries,
            "weekly_context": self.weekly_context,
            "donors": self.donors,
            "donations": self.donations,
            "donation_items": self.donation_items,
            "inventory_lots": self.inventory_lots,
            "distributions": self.distributions,
            "shortage_reports": self.shortage_reports,
        }

    def current_tables(self) -> dict[str, list[dict]]:
        """The current-inventory tables, in foreign-key order. Empty until it is added."""
        return {
            "donations": self.current_donations,
            "donation_items": self.current_donation_items,
            "inventory_lots": self.current_lots,
        }


def fingerprint(data: SyntheticData) -> str:
    blob = json.dumps(data.tables(), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# --- calendar and weather -------------------------------------------------------------------


def _weeks() -> list[date]:
    return [FIRST_WEEK + timedelta(weeks=i) for i in range(N_WEEKS)]


def _holiday_season(week: date) -> bool:
    mid = week + timedelta(days=3)
    return mid.month == 12 or (mid.month == 11 and mid.day >= 20)


# --- generation -----------------------------------------------------------------------------


def generate(seed: int = DEFAULT_SEED) -> SyntheticData:
    return generate_with_truth(seed)[0]


def generate_with_truth(seed: int = DEFAULT_SEED) -> tuple[SyntheticData, np.ndarray]:
    """The history plus the true demand it was built from, shape (pantry, category, week) in
    pounds (pantry and category ids are index + 1). Observed distributions are this demand capped
    by supply. The truth is for scoring a forecast after the fact, never for training one."""
    rng = np.random.default_rng(seed)
    data = SyntheticData()
    weeks = _weeks()
    doy = np.array([(w + timedelta(days=3)).timetuple().tm_yday for w in weeks])
    season = np.sin(2 * math.pi * (doy - 110) / 365)  # peaks in mid July

    pantry_county = _make_pantries(rng, data)
    baseline = np.array([p["baseline_households"] for p in data.pantries], dtype=float)
    temp, precip = _make_weather(rng, data, weeks, doy, season)
    school, benefit = _make_calendar_flags(weeks)
    _weekly_context_rows(data, weeks, temp, precip, school, benefit)
    holiday_season = np.array([_holiday_season(w) for w in weeks])

    # --- demand ---------------------------------------------------------------------------
    t_p, p_p = temp[pantry_county], precip[pantry_county]  # (P, W)
    hot, cold, wet = t_p > 85, t_p < 25, p_p > 1.5
    trend = 1 + 0.04 * (np.arange(N_WEEKS) / 52)
    hh_factor = (
        np.where(benefit[pantry_county], 1.15, 1.0)
        * np.where(school[pantry_county], 1.10, 1.0)
        * (1 - 0.05 * hot) * (1 - 0.10 * cold) * (1 - 0.06 * wet)
        * trend
    )  # fmt: skip
    hh_latent = (baseline[:, None] / WEEKS_PER_MONTH) * hh_factor
    hh_latent = hh_latent * rng.lognormal(0, 0.05, hh_latent.shape)

    cat_season = np.ones((C, N_WEEKS))
    for name, amp in {"produce": 0.18, "frozen": -0.10, "canned": -0.12, "dry_goods": -0.05,
                      "beverages": 0.15}.items():  # fmt: skip
        cat_season[CAT_INDEX[name]] = 1 + amp * season
    cat_holiday = np.ones((C, N_WEEKS))
    for name, boost in {"protein": 1.25, "bakery": 1.30, "canned": 1.10, "dairy": 1.08}.items():
        cat_holiday[CAT_INDEX[name]] = np.where(holiday_season, boost, 1.0)
    hot_fx, cold_fx = np.zeros(C), np.zeros(C)
    hot_fx[CAT_INDEX["beverages"]], hot_fx[CAT_INDEX["produce"]] = 0.25, 0.08
    cold_fx[CAT_INDEX["canned"]], cold_fx[CAT_INDEX["dry_goods"]] = 0.10, 0.05
    weather_fx = (
        1 + hot[:, None, :] * hot_fx[None, :, None] + cold[:, None, :] * cold_fx[None, :, None]
    )

    affinity = rng.lognormal(0, 0.15, (N_PANTRIES, C))
    noise = rng.lognormal(0, 0.10, (N_PANTRIES, C, N_WEEKS))
    per_household = (
        LBS_PER_HOUSEHOLD * SHARE[None, :, None] * cat_season[None] * cat_holiday[None]
        * weather_fx * affinity[:, :, None] * noise
    )  # fmt: skip
    demand = hh_latent[:, None, :] * per_household  # (P, C, W) pounds

    # --- supply: warehouse lots -----------------------------------------------------------
    total_demand = demand.sum(axis=0)  # (C, W)
    ratio = SUPPLY_RATIO[:, None] * rng.lognormal(0, SUPPLY_NOISE, (C, N_WEEKS))
    supply = _make_lots(rng, data, weeks, total_demand * ratio)  # usable lbs, (C, W)

    # --- allocation, distribution, shortages ----------------------------------------------
    weight = demand * rng.lognormal(0, ALLOCATION_NOISE, demand.shape)
    allocation = supply[None] * weight / weight.sum(axis=0, keepdims=True)
    distributed = np.round(np.minimum(demand, allocation), 2)
    households = np.maximum(1, np.rint(hh_latent)).astype(int)
    _make_distributions_and_shortages(rng, data, weeks, demand, distributed, households)
    return data, demand


def _make_pantries(rng: np.random.Generator, data: SyntheticData) -> np.ndarray:
    counties = np.repeat(np.arange(len(COUNTY_NAMES)), PANTRIES_PER_COUNTY)
    counties = rng.permutation(counties)  # pantry id -> county index
    raw = rng.lognormal(0, 0.55, N_PANTRIES)
    households = np.maximum(60, np.rint(raw / raw.sum() * TOTAL_HOUSEHOLDS_PER_MONTH)).astype(int)
    for i in range(N_PANTRIES):
        name = COUNTY_NAMES[counties[i]]
        lat, lon = COUNTIES[name]
        week_lbs = households[i] / WEEKS_PER_MONTH * LBS_PER_HOUSEHOLD
        cold_share = SHARE[[CAT_INDEX[c] for c in ("produce", "dairy", "protein", "frozen")]].sum()
        data.pantries.append(
            {
                "id": i + 1,
                "name": f"Pantry {i + 1:02d}",
                "county": name,
                "latitude": round(float(lat + rng.normal(0, 0.12)), 6),
                "longitude": round(float(lon + rng.normal(0, 0.12)), 6),
                "cold_capacity_lbs": int(round(week_lbs * cold_share * 1.4 / 10) * 10),
                "dry_capacity_lbs": int(round(week_lbs * (1 - cold_share) * 2.5 / 10) * 10),
                "baseline_households": int(households[i]),
            }
        )
    return counties


def _make_weather(rng, data, weeks, doy, season) -> tuple[np.ndarray, np.ndarray]:
    K = len(COUNTY_NAMES)
    temp = np.zeros((K, N_WEEKS))
    precip = np.zeros((K, N_WEEKS))
    for k, county in enumerate(COUNTY_NAMES):
        offset = -(COUNTIES[county][0] - 40.0) * 6  # northern counties run cooler
        temp[k] = np.round(52 + 24 * season + offset + rng.normal(0, 4.5, N_WEEKS), 1)
        wet_season = 1 + 0.25 * np.sin(2 * math.pi * (doy - 60) / 365)
        precip[k] = np.round(rng.gamma(0.9, 0.8, N_WEEKS) * wet_season, 2)
    return temp, precip


def _make_calendar_flags(weeks) -> tuple[np.ndarray, np.ndarray]:
    K = len(COUNTY_NAMES)
    school = np.zeros((K, N_WEEKS), dtype=bool)
    benefit = np.zeros((K, N_WEEKS), dtype=bool)
    for k, county in enumerate(COUNTY_NAMES):
        for w, week in enumerate(weeks):
            school[k, w] = school_holiday(county, week)
            benefit[k, w] = benefit_week(county, week)
    return school, benefit


def _weekly_context_rows(data, weeks, temp, precip, school, benefit) -> None:
    for w, week in enumerate(weeks):
        for k, county in enumerate(COUNTY_NAMES):
            data.weekly_context.append(
                {
                    "id": len(data.weekly_context) + 1,
                    "county": county,
                    "week_start": week,
                    "avg_temp_f": float(temp[k, w]),
                    "precip_in": float(precip[k, w]),
                    "school_holiday": bool(school[k, w]),
                    "benefit_week": bool(benefit[k, w]),
                }
            )


def _make_lots(rng, data, weeks, target_usable) -> np.ndarray:
    """Create donors, donations, items and lots. Returns usable pounds per (category, week):
    what was received minus what expired."""
    for i, (name, kind) in enumerate(DONORS):
        data.donors.append({"id": i + 1, "name": name, "donor_type": kind})
    by_type = {t: [i + 1 for i, (_, k) in enumerate(DONORS) if k == t] for t in DONOR_AFFINITY}
    types = list(DONOR_AFFINITY)

    usable = np.zeros((C, N_WEEKS))
    pending: dict[tuple[int, date], list[int]] = {}  # (donor_id, received_date) -> lot ids
    lot_rows: list[dict] = []
    for w, week in enumerate(weeks):
        pending = {}
        for c, cat in enumerate(CATEGORY_NAMES):
            perishable = bool(PERISHABLE[c])
            n_lots = int(rng.integers(3, 7) if perishable else rng.integers(1, 4))
            shares = rng.dirichlet(np.full(n_lots, 2.0))
            # Receive enough that the usable weight lands near the target after expiry.
            received_total = target_usable[c, w] / (1 - SPOILAGE[c])
            for share in shares:
                received = max(1.0, round(float(share * received_total), 2))
                received_date = week + timedelta(days=int(rng.integers(0, 5)))
                storage = _storage_type(rng, cat)
                short_lived = perishable and storage != "frozen"
                if short_lived:
                    shelf_days, base = int(rng.integers(3, 8)), SPOILAGE[c]
                elif perishable:
                    shelf_days, base = int(rng.integers(90, 181)), LONG_LIFE_SPOILAGE
                else:
                    shelf_days, base = int(rng.integers(120, 541)), LONG_LIFE_SPOILAGE
                lost = min(0.7, float(base * rng.gamma(1.5, 1 / 1.5)))
                expired = round(received * lost, 2)
                usable[c, w] += received - expired
                affinity = np.array([DONOR_AFFINITY[t][c] for t in types], dtype=float)
                kind = types[int(rng.choice(len(types), p=affinity / affinity.sum()))]
                donor_id = int(rng.choice(by_type[kind]))
                lot_id = len(lot_rows) + 1
                unit, lbs_per_unit = UNITS[cat]
                lot_rows.append(
                    {
                        "id": lot_id,
                        "donation_item_id": lot_id,  # one item per lot
                        "category_id": c + 1,
                        "storage_type": storage,
                        "received_lbs": received,
                        "remaining_lbs": 0.0,  # history is closed: used or expired
                        "expired_lbs": expired,
                        "received_date": received_date,
                        "expiry_date": received_date + timedelta(days=shelf_days),
                        "status": "depleted",
                        "_donor_id": donor_id,
                        "_item": {
                            "name": ITEM_NAMES[cat][int(rng.integers(0, len(ITEM_NAMES[cat])))],
                            "unit": unit,
                            "quantity": max(0.01, round(received / lbs_per_unit, 2)),
                        },
                    }
                )
                pending.setdefault((donor_id, received_date), []).append(lot_id)
        _emit_donations(rng, data, lot_rows, pending)
    for lot in lot_rows:
        lot.pop("_donor_id")
        lot.pop("_item")
        data.inventory_lots.append(lot)
    return np.round(usable, 2)


def _storage_type(rng, cat: str) -> str:
    if cat == "produce":
        return "refrigerated" if rng.random() < 0.7 else "ambient"
    if cat == "dairy":
        return "refrigerated"
    if cat == "protein":
        return "refrigerated" if rng.random() < 0.75 else "frozen"
    if cat == "frozen":
        return "frozen"
    return "ambient"


def _emit_donations(rng, data, lot_rows, pending) -> None:
    """Group one week's lots into donations of at most 4 items per donor and day."""
    for (donor_id, received_date), lot_ids in sorted(pending.items()):
        for start in range(0, len(lot_ids), 4):
            donation_id = len(data.donations) + 1
            received_at = datetime(
                received_date.year, received_date.month, received_date.day,
                int(rng.integers(9, 17)), int(rng.integers(0, 60)), tzinfo=UTC,
            )  # fmt: skip
            data.donations.append(
                {
                    "id": donation_id,
                    "donor_id": donor_id,
                    "source_type": "historical",
                    "file_key": None,
                    "status": "confirmed",
                    "raw_llm_output": None,
                    "model_id": None,
                    "latency_ms": None,
                    "received_at": received_at,
                    "created_by": None,
                }
            )
            for lot_id in lot_ids[start : start + 4]:
                lot = lot_rows[lot_id - 1]
                data.donation_items.append(
                    {
                        "id": lot_id,
                        "donation_id": donation_id,
                        "name": lot["_item"]["name"],
                        "category_id": lot["category_id"],
                        "quantity": lot["_item"]["quantity"],
                        "unit": lot["_item"]["unit"],
                        "estimated_weight_lbs": lot["received_lbs"],
                        "expiry_date": lot["expiry_date"],
                        "storage_type": lot["storage_type"],
                        "confidence": {},
                        "edited": False,
                    }
                )


def _make_distributions_and_shortages(rng, data, weeks, demand, distributed, households) -> None:
    short = distributed < SHORTAGE_THRESHOLD * demand
    propensity = np.clip(rng.normal(1.0, 0.3, N_PANTRIES), 0.4, 1.6)
    p_report = np.clip(
        REPORT_PROBABILITY * propensity[:, None, None] * REPORT_BY_CATEGORY[None, :, None], 0, 1
    )
    reported = short & (rng.random(demand.shape) < p_report)
    turned_away_share = rng.uniform(0.15, 0.50, demand.shape)
    ratio = np.divide(distributed, demand, out=np.ones_like(demand), where=demand > 0)

    for w, week in enumerate(weeks):
        for p in range(N_PANTRIES):
            for c in range(C):
                data.distributions.append(
                    {
                        "id": len(data.distributions) + 1,
                        "pantry_id": p + 1,
                        "category_id": c + 1,
                        "week_start": week,
                        "lbs": float(distributed[p, c, w]),
                        "households": int(households[p, w]),
                    }
                )
                if reported[p, c, w]:
                    r = ratio[p, c, w]
                    data.shortage_reports.append(
                        {
                            "id": len(data.shortage_reports) + 1,
                            "pantry_id": p + 1,
                            "category_id": c + 1,
                            "week_start": week,
                            "severity": 3 if r < 0.5 else 2 if r < 0.75 else 1,
                            "households_turned_away": int(
                                round(households[p, w] * (1 - r) * turned_away_share[p, c, w])
                            ),
                            "notes": None,
                            "reported_by": None,
                        }
                    )


def summarize(data: SyntheticData) -> dict[str, float]:
    """Headline numbers for the seed script's report."""
    perishable_ids = {
        i + 1 for i, name in enumerate(CATEGORY_NAMES) if name in PERISHABLE_CATEGORIES
    }
    lots = [lot for lot in data.inventory_lots if lot["category_id"] in perishable_ids]
    pairs = {(r["pantry_id"], r["week_start"]) for r in data.shortage_reports}
    top = sum(r["category_id"] in (CAT_INDEX["protein"] + 1, CAT_INDEX["produce"] + 1)
              for r in data.shortage_reports)  # fmt: skip
    return {
        "spoilage_pct": 100
        * sum(lot["expired_lbs"] for lot in lots)
        / sum(lot["received_lbs"] for lot in lots),
        "pantry_week_stockout_pct": 100 * len(pairs) / (N_PANTRIES * N_WEEKS),
        "category_week_stockout_pct": 100 * len(data.shortage_reports) / (N_PANTRIES * C * N_WEEKS),
        "protein_produce_share_pct": 100 * top / len(data.shortage_reports),
    }


if __name__ == "__main__":
    seed = DEFAULT_SEED
    result = generate(seed)
    print(f"seed={seed} fingerprint={fingerprint(result)[:16]}")
    for name, rows in result.tables().items():
        print(f"  {name:18s} {len(rows):>8,}")
    for key, value in summarize(result).items():
        print(f"  {key:28s} {value:6.2f}")


# --- stock on hand for the forecast week ------------------------------------------------------

CURRENT_INVENTORY_SEED = 6161


def add_current_inventory(data: SyntheticData, seed: int = CURRENT_INVENTORY_SEED) -> SyntheticData:
    """Add the lots on hand at the start of the week after the history, so there is stock to
    allocate. Sized like the history's weekly supply: the average pounds handed out per category
    over the last four weeks times that category's supply ratio. Fresh food arrived one to three
    days before the forecast Monday and expires 6 to 13 days after it. The history is untouched.
    """
    rng = np.random.default_rng(seed)
    last_week = max(d["week_start"] for d in data.distributions)
    monday = last_week + timedelta(weeks=1)
    recent = sorted({d["week_start"] for d in data.distributions})[-4:]
    weekly = dict.fromkeys(range(1, C + 1), 0.0)
    for d in data.distributions:
        if d["week_start"] in recent:
            weekly[d["category_id"]] += d["lbs"] / len(recent)

    by_type = {t: [i + 1 for i, (_, k) in enumerate(DONORS) if k == t] for t in DONOR_AFFINITY}
    types = list(DONOR_AFFINITY)
    next_donation = max(d["id"] for d in data.donations) + 1
    next_lot = max(lot["id"] for lot in data.inventory_lots) + 1

    lots: list[dict] = []
    pending: dict[tuple[int, date], list[int]] = {}
    for c, cat in enumerate(CATEGORY_NAMES):
        perishable = bool(PERISHABLE[c])
        total = weekly[c + 1] * SUPPLY_RATIO[c] * float(rng.lognormal(0, 0.05))
        n_lots = int(rng.integers(3, 7) if perishable else rng.integers(1, 4))
        for share in rng.dirichlet(np.full(n_lots, 2.0)):
            lbs = max(1.0, round(float(share * total), 2))
            storage = _storage_type(rng, cat)
            received = monday - timedelta(days=int(rng.integers(1, 4)))
            if perishable and storage != "frozen":
                days_left = int(rng.integers(6, 14))
            elif perishable:
                days_left = int(rng.integers(90, 181))
            else:
                days_left = int(rng.integers(120, 541))
            affinity = np.array([DONOR_AFFINITY[t][c] for t in types], dtype=float)
            kind = types[int(rng.choice(len(types), p=affinity / affinity.sum()))]
            donor_id = int(rng.choice(by_type[kind]))
            unit, lbs_per_unit = UNITS[cat]
            lot_id = next_lot + len(lots)
            lots.append(
                {
                    "id": lot_id,
                    "donation_item_id": lot_id,
                    "category_id": c + 1,
                    "storage_type": storage,
                    "received_lbs": lbs,
                    "remaining_lbs": lbs,  # nothing has been sent out yet
                    "expired_lbs": 0.0,
                    "received_date": received,
                    "expiry_date": monday + timedelta(days=days_left),
                    "status": "available",
                    "_donor_id": donor_id,
                    "_item": {
                        "name": ITEM_NAMES[cat][int(rng.integers(0, len(ITEM_NAMES[cat])))],
                        "unit": unit,
                        "quantity": max(0.01, round(lbs / lbs_per_unit, 2)),
                    },
                }
            )
            pending.setdefault((donor_id, received), []).append(lot_id)

    donations, items = [], []
    for (donor_id, received), lot_ids in sorted(pending.items()):
        for start in range(0, len(lot_ids), 4):
            donation_id = next_donation + len(donations)
            donations.append(
                {
                    "id": donation_id,
                    "donor_id": donor_id,
                    "source_type": "historical",
                    "file_key": None,
                    "original_filename": "seeded-current-inventory",
                    "status": "confirmed",
                    "raw_llm_output": None,
                    "model_id": None,
                    "latency_ms": None,
                    "received_at": datetime(
                        received.year, received.month, received.day, 10, 0, tzinfo=UTC
                    ),
                    "created_by": None,
                }
            )
            for lot_id in lot_ids[start : start + 4]:
                lot = next(x for x in lots if x["id"] == lot_id)
                items.append(
                    {
                        "id": lot_id,
                        "donation_id": donation_id,
                        "name": lot["_item"]["name"],
                        "category_id": lot["category_id"],
                        "quantity": lot["_item"]["quantity"],
                        "unit": lot["_item"]["unit"],
                        "estimated_weight_lbs": lot["received_lbs"],
                        "expiry_date": lot["expiry_date"],
                        "storage_type": lot["storage_type"],
                        "confidence": {},
                        "edited": False,
                    }
                )
    for lot in lots:
        lot.pop("_donor_id")
        lot.pop("_item")
    data.current_donations, data.current_donation_items, data.current_lots = donations, items, lots
    return data
