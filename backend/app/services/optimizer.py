"""Expiry-aware allocation as a linear program (OR-Tools GLOP).

Decision variable: x[lot, pantry], the pounds of an inventory lot sent to a pantry for the
forecast week. The objective, in order of importance:

1. **Meet forecast demand, fairly.** Each pantry and category earns at least 1.0 per pound
   delivered up to its P50 forecast, then `band_weight` (0.5) per pound between P50 and P90. The
   P50 part is split into `coverage_tiers` equal slices, and each slice earns `coverage_step` less
   per pound than the one before (the first slice of everyone's forecast is worth the most). When
   stock is short, a pound is therefore worth most to the pantry that has received the smallest
   share of its own forecast, so scarce stock is spread by share of demand instead of filled
   nearest-first. The step is always larger than the biggest distance difference between pantries
   (see `tier_step`), so distance can break a tie but can never outweigh unmet demand. The P50 to
   P90 band is what keeps pantries from running short when stock allows: aiming only at P50
   leaves a pantry short about half the time, because the forecast is off by more than 10% about
   that often.
2. **Ship the soonest-expiring stock first.** Each pound of a lot earns a bonus that grows from 0
   (10 or more days left) to `urgency_weight` (0.20, expiring on the delivery day). Among lots of
   the same category, the one closest to expiry fills demand first, and an urgent lot may go past
   P50 up to P90 rather than spoil.
3. **Prefer nearer pantries.** A small penalty per pound per mile from the warehouse, small enough
   that meeting demand always wins.

Constraints: a lot cannot ship more than it has; a pantry's cold (refrigerated and frozen) and dry
(ambient) intake cannot exceed its storage capacity; and a pantry cannot receive more than its P90
forecast in any category. The caller supplies capacities and forecasts net of anything already
approved for the week.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ortools.linear_solver import pywraplp

EARTH_RADIUS_MILES = 3958.8
EPSILON = 1e-6


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class LotIn:
    id: int
    category_id: int
    storage_type: str  # ambient | refrigerated | frozen
    remaining_lbs: float
    expiry_date: date | None  # None: no expiry date (shelf-stable)


@dataclass(frozen=True)
class PantryIn:
    id: int
    miles: float  # from the warehouse
    cold_capacity_lbs: float  # intake limit this week for refrigerated and frozen stock
    dry_capacity_lbs: float  # intake limit this week for ambient stock


@dataclass(frozen=True)
class DemandIn:
    p50: float
    p90: float


@dataclass(frozen=True)
class OptimizerParams:
    band_weight: float = 0.5
    urgency_weight: float = 0.20
    urgency_horizon_days: int = 10
    distance_penalty_per_mile: float = 0.0005
    coverage_tiers: int = 10  # slices of P50; the granularity of the fairness (10% of forecast)
    coverage_step: float = 0.02  # reward difference between neighbouring slices, at least
    min_shipment_lbs: float = 1.0


@dataclass(frozen=True)
class Shipment:
    lot_id: int
    pantry_id: int
    lbs: float


@dataclass
class Solution:
    status: str
    shipments: list[Shipment] = field(default_factory=list)
    excluded_lot_ids: list[int] = field(default_factory=list)  # expire before delivery
    demand_met_p50: float = 0.0
    n_variables: int = 0
    n_constraints: int = 0


class OptimizerError(Exception):
    """The solver could not find an optimal allocation."""


def tier_step(params: OptimizerParams, miles: list[float]) -> float:
    """Reward gap between neighbouring coverage slices. It is at least `coverage_step` and always
    1.5 times the largest distance cost difference between two pantries, so moving a pound to a
    less-covered pantry always beats the distance it saves, however the penalty is set."""
    spread = (max(miles) - min(miles)) if miles else 0.0
    return max(params.coverage_step, 1.5 * params.distance_penalty_per_mile * spread)


def _round_down(value: float) -> float:
    return math.floor(value * 100 + EPSILON) / 100  # never round up past a limit


def solve(
    lots: list[LotIn],
    pantries: list[PantryIn],
    demand: dict[tuple[int, int], DemandIn],
    delivery_date: date,
    params: OptimizerParams | None = None,
) -> Solution:
    """Allocate lots to pantries for the week. `demand` is keyed by (pantry id, category id)."""
    params = params or OptimizerParams()
    usable = [
        lot
        for lot in lots
        if lot.remaining_lbs > EPSILON
        and (lot.expiry_date is None or lot.expiry_date >= delivery_date)
    ]
    excluded = [
        lot.id
        for lot in lots
        if lot.remaining_lbs > EPSILON
        and lot.expiry_date is not None
        and lot.expiry_date < delivery_date
    ]
    if not usable or not pantries or not demand:
        return Solution("OPTIMAL", excluded_lot_ids=excluded)

    solver = pywraplp.Solver.CreateSolver("GLOP")
    x: dict[tuple[int, int], pywraplp.Variable] = {}
    lots_by_category: dict[int, list[LotIn]] = {}
    for lot in usable:
        lots_by_category.setdefault(lot.category_id, []).append(lot)

    pantry_ids = [p.id for p in pantries]
    for lot in usable:
        for p in pantries:
            want = demand.get((p.id, lot.category_id))
            cap = min(lot.remaining_lbs, want.p90) if want else 0.0
            if cap > EPSILON:
                x[lot.id, p.id] = solver.NumVar(0.0, cap, f"x_{lot.id}_{p.id}")

    # Tiered coverage of P50: tiers[p, c] are the slices, cheapest-to-fill (most valuable) first.
    tiers: dict[tuple[int, int], list[pywraplp.Variable]] = {}
    y2: dict[tuple[int, int], pywraplp.Variable] = {}
    n_tiers = max(1, params.coverage_tiers)
    for (p_id, c_id), want in demand.items():
        if p_id in pantry_ids and c_id in lots_by_category and want.p90 > EPSILON:
            slice_lbs = max(0.0, want.p50) / n_tiers
            tiers[p_id, c_id] = [solver.NumVar(0.0, slice_lbs, "") for _ in range(n_tiers)]
            y2[p_id, c_id] = solver.NumVar(0.0, max(0.0, want.p90 - want.p50), "")

    for lot in usable:  # a lot cannot ship more than it has
        terms = [x[lot.id, p.id] for p in pantries if (lot.id, p.id) in x]
        if terms:
            solver.Add(solver.Sum(terms) <= lot.remaining_lbs)
    for (p_id, c_id), slices in tiers.items():
        inbound = [x[lot.id, p_id] for lot in lots_by_category[c_id] if (lot.id, p_id) in x]
        solver.Add(
            solver.Sum(slices) + y2[p_id, c_id] <= solver.Sum(inbound)
        )  # credit only for what arrives
        solver.Add(solver.Sum(inbound) <= demand[p_id, c_id].p90)  # no more than P90
    for p in pantries:
        cold = [
            x[lot.id, p.id]
            for lot in usable
            if lot.storage_type != "ambient" and (lot.id, p.id) in x
        ]
        dry = [
            x[lot.id, p.id]
            for lot in usable
            if lot.storage_type == "ambient" and (lot.id, p.id) in x
        ]
        if cold:
            solver.Add(solver.Sum(cold) <= p.cold_capacity_lbs)
        if dry:
            solver.Add(solver.Sum(dry) <= p.dry_capacity_lbs)

    miles = {p.id: p.miles for p in pantries}
    step = tier_step(params, [p.miles for p in pantries])
    coverage = []
    for slices in tiers.values():
        for k, var in enumerate(slices):  # slice k is worth 1 + step * (tiers - 1 - k) per pound
            coverage.append(var * (1.0 + step * (n_tiers - 1 - k)))
    objective = solver.Sum(coverage) + params.band_weight * solver.Sum(y2.values())
    terms = []
    for lot in usable:
        days_left = 0 if lot.expiry_date is None else max(0, (lot.expiry_date - delivery_date).days)
        urgent = params.urgency_weight * max(0.0, 1 - days_left / params.urgency_horizon_days)
        if lot.expiry_date is None:
            urgent = 0.0
        for p_id in pantry_ids:
            if (lot.id, p_id) in x:
                terms.append(
                    x[lot.id, p_id] * (urgent - params.distance_penalty_per_mile * miles[p_id])
                )
    solver.Maximize(objective + solver.Sum(terms))

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        raise OptimizerError(f"GLOP returned status {status}")

    shipments = []
    for (lot_id, p_id), var in x.items():
        lbs = _round_down(var.solution_value())
        if lbs >= params.min_shipment_lbs:
            shipments.append(Shipment(lot_id, p_id, lbs))
    shipments.sort(key=lambda s: (s.pantry_id, s.lot_id))
    return Solution(
        "OPTIMAL",
        shipments,
        excluded,
        demand_met_p50=sum(v.solution_value() for slices in tiers.values() for v in slices),
        n_variables=solver.NumVariables(),
        n_constraints=solver.NumConstraints(),
    )
