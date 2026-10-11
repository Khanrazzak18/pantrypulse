"""Replay the last 12 weeks under two allocation policies and compare them.

    python -m eval.allocation_sim          # (make simulate) needs `make backtest` first

Both policies get the same stock (the generator's usable pounds, arriving on the days the lots
were received) and are scored against the same true demand. Stock carries over between weeks, the
warehouse starts empty, and food goes out twice a week, on Wednesday and Friday (the second run
is a re-run, as in the app: it sees only what the Wednesday run left unmet and what arrived
since).

* **Manual rule** (a stand-in for today's spreadsheet-and-phone routine): ship everything on hand,
  split between pantries in proportion to their true demand times a random error (lognormal,
  sigma 0.15). Run 10 times; the report gives the mean and the range.
* **Optimizer**: the code in `app.services.optimizer`, fed the out-of-sample P50/P90 forecasts
  from the backtest (never the true demand).

What this can and cannot show is written into the report itself: it supports the stockout target
and cannot test the spoilage target.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.config import ROOT, get_settings
from app.constants import CATEGORY_NAMES, PERISHABLE_CATEGORIES, WAREHOUSE
from app.db import make_engine
from app.services import optimizer
from scripts.generate_synthetic_data import DEFAULT_SEED, FIRST_WEEK, generate_with_truth

REPORT_PATH = ROOT / "docs/eval/allocation-sim.md"
DELIVERY_WEEKDAYS = (2, 4)  # Wednesday, then a re-run on Friday for lots that arrived since
SHORT_BELOW = 0.90  # a pantry is short in a category when it gets under 90% of its true demand
MANUAL_NOISE = 0.15
MANUAL_RUNS = 10
N_CATEGORIES = len(CATEGORY_NAMES)
PERISHABLE = np.array([c in PERISHABLE_CATEGORIES for c in CATEGORY_NAMES])
TARGETS = {"stockouts": -0.30, "spoilage": 0.08}
BASELINE_SPOILAGE = 0.12


@dataclass
class SimLot:
    category_id: int  # 1-based, as in the database
    storage_type: str
    lbs: float
    arrival: date
    expiry: date | None


@dataclass
class SimWeek:
    monday: date
    truth: np.ndarray  # (pantry, category) true demand in lb
    p50: np.ndarray  # (pantry, category) forecast made before the week
    p90: np.ndarray


@dataclass
class SimInputs:
    pantries: list[optimizer.PantryIn]  # ids 1..P, in order
    lots: list[SimLot]
    weeks: list[SimWeek]


@dataclass
class SimResult:
    short_pantry_weeks: float  # share of pantry-weeks where any category got under 90% of demand
    short_cells: float  # the same, per pantry, category and week
    spoilage_a: float  # expired in the warehouse plus delivered beyond true demand
    spoilage_b: float  # expired in the warehouse only
    over_delivery: float
    warehouse_expiry: float
    delivered_lbs: float = 0.0
    demand_lbs: float = 0.0
    left_in_warehouse_lbs: float = 0.0
    perishable_resolved_lbs: float = 0.0
    short_beyond_p90: float = 0.0  # share of short cells where true demand exceeded the P90
    weekly_short: list[float] = field(default_factory=list)
    # per pantry, summed over the weeks (for fairness): lb delivered, P50 forecast, P50 met
    delivered_by_pantry: np.ndarray | None = None
    p50_by_pantry: np.ndarray | None = None
    p50_met_by_pantry: np.ndarray | None = None
    trip_miles: float = 0.0  # miles from the warehouse, summed over every pantry visited each run
    pound_miles: float = 0.0  # pounds delivered times miles from the warehouse


def simulate(
    inputs: SimInputs,
    policy: str,
    seed: int = 0,
    noise: float = MANUAL_NOISE,
    net_manual: bool = False,
    days: tuple[int, ...] | None = None,
    params: optimizer.OptimizerParams | None = None,
) -> SimResult:
    rng = np.random.default_rng(seed)
    n_p = len(inputs.pantries)
    pending = sorted(inputs.lots, key=lambda lot: lot.arrival)
    stock: list[list] = []  # [SimLot, remaining lbs]
    expired_perishable = over = received_perishable = 0.0
    short_pw = short_cells = cells = beyond_p90 = 0
    delivered_total = demand_total = 0.0
    weekly_short: list[float] = []
    miles = np.array([p.miles for p in inputs.pantries])
    by_delivered, by_p50, by_met = np.zeros(n_p), np.zeros(n_p), np.zeros(n_p)
    trip_miles = 0.0

    for week in inputs.weeks:
        delivered = np.zeros((n_p, N_CATEGORIES))
        cold_used, dry_used = np.zeros(n_p), np.zeros(n_p)
        for weekday in days or DELIVERY_WEEKDAYS:
            delivery = week.monday + timedelta(days=weekday)
            while pending and pending[0].arrival <= delivery:
                lot = pending.pop(0)
                stock.append([lot, lot.lbs])
                if PERISHABLE[lot.category_id - 1]:
                    received_perishable += lot.lbs
            for entry in [e for e in stock if e[0].expiry is not None and e[0].expiry < delivery]:
                if PERISHABLE[entry[0].category_id - 1]:
                    expired_perishable += entry[1]
                stock.remove(entry)
            today = np.zeros((n_p, N_CATEGORIES))
            if policy == "manual":
                for c in range(N_CATEGORIES):
                    on_hand = sum(e[1] for e in stock if e[0].category_id == c + 1)
                    if on_hand <= 0:
                        continue
                    need = week.truth[:, c]
                    if net_manual:  # a coordinator who remembers what already went out today
                        need = np.clip(need - delivered[:, c], 0, None)
                        if need.sum() <= 0:
                            need = week.truth[:, c]
                    weights = need * rng.lognormal(0, noise, n_p)
                    today[:, c] = on_hand * weights / weights.sum()
                for e in stock:
                    e[1] = 0.0
            elif policy == "optimizer":
                lots = [
                    optimizer.LotIn(i, e[0].category_id, e[0].storage_type, e[1], e[0].expiry)
                    for i, e in enumerate(stock)
                    if e[1] > 0
                ]
                # what the app does on a re-run: forecasts and capacity net of what already went
                demand = {}
                for p in range(n_p):
                    for c in range(N_CATEGORIES):
                        p90 = max(0.0, week.p90[p, c] - delivered[p, c])
                        if p90 > 0:
                            p50 = max(0.0, week.p50[p, c] - delivered[p, c])
                            demand[p + 1, c + 1] = optimizer.DemandIn(float(p50), float(p90))
                left_over = [
                    optimizer.PantryIn(
                        p.id,
                        p.miles,
                        max(0.0, p.cold_capacity_lbs - cold_used[i]),
                        max(0.0, p.dry_capacity_lbs - dry_used[i]),
                    )
                    for i, p in enumerate(inputs.pantries)
                ]
                solution = optimizer.solve(lots, left_over, demand, delivery, params)
                for sh in solution.shipments:
                    entry = stock[sh.lot_id]
                    today[sh.pantry_id - 1, entry[0].category_id - 1] += sh.lbs
                    entry[1] -= sh.lbs
                    used = dry_used if entry[0].storage_type == "ambient" else cold_used
                    used[sh.pantry_id - 1] += sh.lbs
            else:
                raise ValueError(f"unknown policy {policy!r}")
            delivered += today
            trip_miles += float(
                miles[today.sum(axis=1) > 1e-6].sum()
            )  # one trip per pantry per run
            stock = [e for e in stock if e[1] > 1e-6]

        by_delivered += delivered.sum(axis=1)
        by_p50 += week.p50.sum(axis=1)
        by_met += np.minimum(delivered, week.p50).sum(axis=1)
        over += float(np.clip(delivered - week.truth, 0, None)[:, PERISHABLE].sum())
        short = delivered < SHORT_BELOW * week.truth
        short_pw += int(short.any(axis=1).sum())
        short_cells += int(short.sum())
        beyond_p90 += int((short & (week.truth > week.p90)).sum())
        cells += short.size
        weekly_short.append(float(short.any(axis=1).mean()))
        delivered_total += float(delivered.sum())
        demand_total += float(week.truth.sum())

    left = sum(e[1] for e in stock if PERISHABLE[e[0].category_id - 1])
    resolved = max(1e-9, received_perishable - left)  # perishable lb that was shipped or expired
    return SimResult(
        short_pantry_weeks=short_pw / (n_p * len(inputs.weeks)),
        short_cells=short_cells / cells,
        spoilage_a=(expired_perishable + over) / resolved,
        spoilage_b=expired_perishable / resolved,
        over_delivery=over / resolved,
        warehouse_expiry=expired_perishable / resolved,
        delivered_lbs=delivered_total,
        demand_lbs=demand_total,
        left_in_warehouse_lbs=left,
        perishable_resolved_lbs=resolved,
        short_beyond_p90=beyond_p90 / short_cells if short_cells else 0.0,
        weekly_short=weekly_short,
        delivered_by_pantry=by_delivered,
        p50_by_pantry=by_p50,
        p50_met_by_pantry=by_met,
        trip_miles=trip_miles,
        pound_miles=float((by_delivered * miles).sum()),
    )


def summarize(results: list[SimResult]) -> dict[str, tuple[float, float, float]]:
    """(mean, min, max) of each headline measure over repeated runs."""
    keys = ("short_pantry_weeks", "short_cells", "spoilage_a", "spoilage_b", "over_delivery")
    return {k: (np.mean(v := [getattr(r, k) for r in results]), min(v), max(v)) for k in keys}


# --- loading the inputs ------------------------------------------------------------------------


def load_inputs(engine) -> tuple[SimInputs, int]:
    data, truth = generate_with_truth(DEFAULT_SEED)
    with engine.connect() as conn:
        run_id = conn.execute(
            text(
                "SELECT id FROM forecast_runs WHERE kind='backtest' AND status='completed' "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            )
        ).scalar()
        if run_id is None:
            raise SystemExit("No backtest found. Run `make backtest` first.")
        fc = pd.read_sql(
            text(
                "SELECT pantry_id, category_id, week_start, p50_lbs::float8 AS p50, "
                "p90_lbs::float8 AS p90 FROM forecasts WHERE forecast_run_id = :r"
            ),
            conn,
            params={"r": run_id},
        )
        pantries = pd.read_sql(
            text(
                "SELECT id, latitude::float8 AS lat, longitude::float8 AS lon, "
                "cold_capacity_lbs, dry_capacity_lbs FROM pantries ORDER BY id"
            ),
            conn,
        )
    fc["week_start"] = pd.to_datetime(fc["week_start"]).dt.date
    mondays = sorted(fc["week_start"].unique())
    n_p = len(pantries)
    weeks = []
    for monday in mondays:
        sub = fc[fc["week_start"] == monday]
        p50, p90 = np.zeros((n_p, N_CATEGORIES)), np.zeros((n_p, N_CATEGORIES))
        p50[sub.pantry_id - 1, sub.category_id - 1] = sub.p50
        p90[sub.pantry_id - 1, sub.category_id - 1] = sub.p90
        idx = (monday - FIRST_WEEK).days // 7
        weeks.append(SimWeek(monday, truth[:, :, idx], p50, p90))
    first = mondays[0]
    lots = [
        SimLot(
            category_id=lot["category_id"],
            storage_type=lot["storage_type"],
            lbs=float(lot["received_lbs"]) - float(lot["expired_lbs"]),  # usable pounds
            arrival=lot["received_date"],
            expiry=lot["expiry_date"],
        )
        for lot in data.inventory_lots
        if lot["received_date"] >= first
    ]
    return (
        SimInputs(
            pantries=[
                optimizer.PantryIn(
                    id=int(r.id),
                    miles=optimizer.haversine_miles(*WAREHOUSE, r.lat, r.lon),
                    cold_capacity_lbs=float(r.cold_capacity_lbs),
                    dry_capacity_lbs=float(r.dry_capacity_lbs),
                )
                for r in pantries.itertuples()
            ],
            lots=lots,
            weeks=weeks,
        ),
        int(run_id),
    )


# --- the report --------------------------------------------------------------------------------


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def relative(new: float, old: float) -> str:
    return f"{(new - old) / old * 100:+.0f}%" if old else "n/a"


SCHEDULES = {
    "Wednesday and Friday (primary)": (2, 4),
    "Friday only (everything that arrived Monday to Friday)": (4,),
    "Wednesday only (stock that arrived by Wednesday)": (2,),
}


def _mean_of(results: list[SimResult]) -> SimResult:
    return SimResult(
        **{
            k: float(np.mean([getattr(r, k) for r in results]))
            for k in SimResult.__dataclass_fields__
            if k != "weekly_short"
        }
    )


def write_report(inputs: SimInputs, run_id: int, path: Path = REPORT_PATH) -> dict:
    manual = [simulate(inputs, "manual", seed=s) for s in range(MANUAL_RUNS)]
    opt = simulate(inputs, "optimizer")
    m = summarize(manual)
    cut = (opt.short_pantry_weeks - m["short_pantry_weeks"][0]) / m["short_pantry_weeks"][0]
    stock_met = cut <= TARGETS["stockouts"]
    grid = []
    for name, days in SCHEDULES.items():
        plain = _mean_of([simulate(inputs, "manual", seed=s, days=days) for s in range(5)])
        netted = _mean_of(
            [simulate(inputs, "manual", seed=s, days=days, net_manual=True) for s in range(5)]
        )
        grid.append((name, plain, netted, simulate(inputs, "optimizer", days=days)))
    sensitivity = {
        sigma: np.mean(
            [simulate(inputs, "manual", seed=s, noise=sigma).short_pantry_weeks for s in range(5)]
        )
        for sigma in (0.0, 0.15, 0.30, 0.50)
    }
    first, last = inputs.weeks[0].monday, inputs.weeks[-1].monday
    stock_in = sum(lot.lbs for lot in inputs.lots)

    if stock_met:
        verdict = "met"
    elif cut < 0:
        verdict = "not met (fewer shortages, but by less than 30%)"
    else:
        verdict = "not met (the optimizer was not better than the manual rule)"

    lines = [
        "# Allocation simulation",
        "",
        f"- Run: {pd.Timestamp.now():%Y-%m-%d %H:%M}",
        f"- Window: {len(inputs.weeks)} weeks, {first} to {last} (the weeks of backtest run "
        f"{run_id}); food goes out on Wednesday and Friday",
        f"- Stock: {len(inputs.lots)} lots, {stock_in:,.0f} lb usable, arriving on their real "
        "received dates; the warehouse starts empty and unshipped stock carries over",
        f"- Pantries: {len(inputs.pantries)}; true demand comes from the data generator and is "
        "used only to score the result (and by the manual rule, below)",
        "",
        "## What this simulation can and cannot tell us",
        "",
        "**It can test the stockout target. It cannot test the spoilage target.**",
        "",
        "The stockout comparison is meaningful in principle because the data generator's "
        "*demand* is real structure the policies must respond to: a policy that sends food where "
        "it is needed meets more demand, and one that guesses wrong leaves pantries short. How "
        "much the optimizer helps depends on how good the manual rule is assumed to be, which "
        "nobody has measured; see the results and sensitivity tables.",
        "",
        "The spoilage target (12% down to under 8%) cannot be tested on this data, because the "
        "generator draws spoilage for each lot independently of how the food is allocated: "
        "how much of a lot expires is decided when the lot is created, before any allocation "
        "exists. Allocation therefore has no way to change the spoilage in the history, and the "
        "12% baseline is a property of the generator's settings, not of anyone's allocation "
        "decisions. The spoilage numbers below come only from the simulation's own bookkeeping of "
        "food that expires in the warehouse or is sent in excess of need. They are reported for "
        "completeness, are not evidence for or against the 8% target, and should not go into a "
        "grant report.",
        "",
        "**What a real pilot would need to measure to test spoilage:**",
        "",
        "- Lot-level records of pounds received, pounds shipped to pantries, pounds distributed to "
        "households and pounds discarded, each with its date, for the period before the optimizer "
        "is used (at least one season) and during the pilot.",
        "- The cause of every discard (expired in the warehouse, expired at the pantry, damaged), "
        "so spoilage caused by allocation can be separated from spoilage that no allocation could "
        "have prevented.",
        "- A comparison that controls for what was donated: pilot pantries or counties against "
        "comparison pantries in the same weeks, or a stepped rollout across pantries, with the "
        "perishable mix and shelf life at receipt recorded.",
        "- Pantry-side reports of food that expired after delivery, since sending food to a pantry "
        "that cannot use it in time only moves the waste.",
        "",
        "## Results",
        "",
        f"Primary setup: deliveries on Wednesday and Friday. Manual rule: mean of {MANUAL_RUNS} "
        "runs (range in brackets). Optimizer: one run (it is deterministic).",
        "",
        "| Measure | Manual rule | Optimizer | Change |",
        "| --- | --- | --- | --- |",
        f"| Pantry-weeks with a shortage (any category under {SHORT_BELOW:.0%} of demand) | "
        f"{pct(m['short_pantry_weeks'][0])} ({pct(m['short_pantry_weeks'][1])} to "
        f"{pct(m['short_pantry_weeks'][2])}) | {pct(opt.short_pantry_weeks)} | "
        f"{relative(opt.short_pantry_weeks, m['short_pantry_weeks'][0])} |",
        f"| Pantry-category-weeks short | {pct(m['short_cells'][0])} ({pct(m['short_cells'][1])} "
        f"to {pct(m['short_cells'][2])}) | {pct(opt.short_cells)} | "
        f"{relative(opt.short_cells, m['short_cells'][0])} |",
        "| Perishable loss, definition A (expired in the warehouse plus sent beyond need) | "
        f"{pct(m['spoilage_a'][0])} ({pct(m['spoilage_a'][1])} to {pct(m['spoilage_a'][2])}) | "
        f"{pct(opt.spoilage_a)} | {relative(opt.spoilage_a, m['spoilage_a'][0])} |",
        "| Perishable loss, definition B (expired in the warehouse only) | "
        f"{pct(m['spoilage_b'][0])} ({pct(m['spoilage_b'][1])} to {pct(m['spoilage_b'][2])}) | "
        f"{pct(opt.spoilage_b)} | {relative(opt.spoilage_b, m['spoilage_b'][0])} |",
        "",
        f"**Stockout target (30% fewer shortages): {verdict}.** Pantry-weeks with a shortage went "
        f"from {pct(m['short_pantry_weeks'][0])} to {pct(opt.short_pantry_weeks)}, a change of "
        f"{cut * 100:+.1f}%.",
        "",
        f"Why the optimizer still runs short: {pct(opt.short_beyond_p90, 0)} of its short "
        "pantry-category-weeks were weeks when true demand was above the P90 forecast, which the "
        "optimizer never sends beyond (a rule of the design). The manual rule is not capped, and "
        f"on average it ships {m_delivery(manual):.0%} of true demand because the stock on hand "
        "exceeds demand in these data.",
        "",
        "Spoilage: no verdict, for the reason above. Definition A counts food that expires in the "
        "warehouse plus food sent to a pantry beyond its true demand (assumed to go to waste). "
        "Definition B counts only warehouse expiry, which flatters the manual rule because it ships "
        "everything the day it is decided, so little waits long enough to expire. The optimizer "
        "keeps stock back when pantries are already covered up to their P90 forecast, which is why "
        "B can be higher for it. Both are shown so neither choice hides the other.",
        "",
        "## The result depends on the assumptions",
        "",
        "Pantry-weeks with a shortage, under different delivery schedules and two versions of the "
        'manual rule. "Netted" is a coordinator who also remembers what already went out that '
        "week when splitting the Friday delivery.",
        "",
        "| Schedule | Manual (as above) | Manual, netted | Optimizer |",
        "| --- | --- | --- | --- |",
    ]
    for name, plain, netted, optimized in grid:
        lines.append(
            f"| {name} | {pct(plain.short_pantry_weeks)} | {pct(netted.short_pantry_weeks)} | "
            f"{pct(optimized.short_pantry_weeks)} |"
        )
    beats_plain = sum(o.short_pantry_weeks < p.short_pantry_weeks for _, p, _, o in grid)
    beats_netted = sum(o.short_pantry_weeks < n.short_pantry_weeks for _, _, n, o in grid)
    lines += [
        "",
        f"The optimizer had fewer shortage pantry-weeks than the manual rule in {beats_plain} of "
        f"{len(grid)} schedules, and than the netted manual rule in {beats_netted} of "
        f"{len(grid)}. So this simulation does not give a robust stockout reduction of 30%: the "
        "size of the effect, and its sign, depends on how good the current process is and how "
        "often food goes out, neither of which has been measured. A pilot would have to measure "
        "them.",
        "",
        "Wednesday-only delivery is shown to make a point, not as a plan: short-lived stock that "
        "arrives on Thursday or Friday expires before the next Wednesday, so both policies look "
        "far worse. That is a scheduling effect, not an allocation one.",
        "",
        "## Sensitivity to the manual rule's error",
        "",
        "The manual rule's error is an assumption (how well a coordinator's split follows true "
        "demand). Primary schedule, pantry-weeks with a shortage:",
        "",
        "| Error (lognormal sigma) | Manual | Optimizer |",
        "| --- | --- | --- |",
    ]
    for sigma, value in sensitivity.items():
        lines.append(f"| {sigma:.2f} | {pct(value)} | {pct(opt.short_pantry_weeks)} |")
    lines += [
        "",
        "The 0.15 used above is a judgment, not a measurement of Harvest Bridge's coordinators. "
        "For scale, the seasonal-naive baseline in the forecast backtest, which is roughly what a "
        "person working from last year's numbers could do, has an error of about 14%.",
        "",
        "## Method notes and limits",
        "",
        "- A pantry is short in a category when it receives under 90% of that week's true demand.",
        "- Manual rule: ships everything on hand, split between pantries in proportion to true "
        "demand times a lognormal error. It uses true demand, which no coordinator has; the "
        "optimizer uses only the forecasts the backtest made before each week. This favors the "
        "manual rule on information.",
        "- The manual rule ignores pantry storage capacity; the optimizer respects it.",
        "- Food goes out on Wednesday, and again on Friday for lots that arrived since (a re-run, "
        "as in the app: forecasts and pantry capacity are net of what already went). A lot that "
        "arrives on the weekend waits for the next Wednesday. Food a pantry gets beyond its true "
        "demand counts as lost in definition A.",
        "- Perishable percentages are of perishable pounds that were shipped or expired during the "
        f"window ({opt.perishable_resolved_lbs:,.0f} lb for the optimizer); stock still in the "
        "warehouse at the end is left out so neither policy is charged for food it has not had "
        "time to handle.",
        "- The one optimizer setting chosen with help from this simulation is the reward for "
        "demand between P50 and P90 (0.5 of a pound's value). A prototype compared 0, 0.3, 0.6 and "
        "0.9 on this same data, and 0 (aim at P50 only) was clearly worse. The other weights "
        "(urgency, distance) were set by reasoning and not tuned. The result therefore is not an "
        "untouched out-of-sample test of the optimizer.",
        "- Demand, supply and spoilage are synthetic. These numbers show how the method behaves on "
        "a simulated food bank, not what Harvest Bridge would see.",
        "",
    ]
    path.write_text("\n".join(lines))
    return {"manual": m, "optimizer": opt, "cut": cut, "met": stock_met, "grid": grid}


def m_delivery(manual: list[SimResult]) -> float:
    return float(np.mean([r.delivered_lbs / r.demand_lbs for r in manual]))


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    inputs, run_id = load_inputs(make_engine(get_settings().database_url))
    out = write_report(inputs, run_id)
    opt, m = out["optimizer"], out["manual"]
    print(f"Report written to {REPORT_PATH}")
    print(
        f"Shortage pantry-weeks: manual {pct(m['short_pantry_weeks'][0])}  optimizer "
        f"{pct(opt.short_pantry_weeks)}  ({out['cut'] * 100:+.1f}%)"
    )
    print(f"Perishable loss A: manual {pct(m['spoilage_a'][0])}  optimizer {pct(opt.spoilage_a)}")
    print(f"Perishable loss B: manual {pct(m['spoilage_b'][0])}  optimizer {pct(opt.spoilage_b)}")


if __name__ == "__main__":
    main()
