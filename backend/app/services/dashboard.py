"""Impact dashboard numbers, straight from the database.

Households are counted once per pantry-week: every category row of a pantry-week carries the same
household count, so summing the rows would multiply it by the number of categories.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.constants import CATEGORY_NAMES
from app.errors import ApiError

MAX_WEEKS = 260
DEFAULT_WEEKS = 26


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weeks_between(start: date, end: date) -> list[date]:
    return [start + timedelta(weeks=k) for k in range((end - start).days // 7 + 1)]


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def data_bounds(db: Session) -> tuple[date | None, date | None]:
    row = db.execute(text("SELECT min(week_start), max(week_start) FROM distributions")).one()
    return row[0], row[1]


def resolve_range(
    db: Session, start: date | None, end: date | None, today: date
) -> tuple[date, date, date | None, date | None]:
    """Snap to Mondays and fill in defaults (the last 26 weeks that have data)."""
    data_start, data_end = data_bounds(db)
    end_week = monday_of(end) if end else (data_end or monday_of(today))
    start_week = monday_of(start) if start else end_week - timedelta(weeks=DEFAULT_WEEKS - 1)
    if start_week > end_week:
        raise ApiError(
            422,
            "validation_error",
            "Some fields are invalid.",
            [{"field": "start", "message": "The start date must not be after the end date.",
              "type": "value_error"}],
        )  # fmt: skip
    if (end_week - start_week).days // 7 + 1 > MAX_WEEKS:
        raise ApiError(
            422,
            "validation_error",
            "Some fields are invalid.",
            [{"field": "start", "message": f"Choose a range of at most {MAX_WEEKS} weeks.",
              "type": "value_error"}],
        )  # fmt: skip
    return start_week, end_week, data_start, data_end


def metrics(db: Session, start: date, end: date) -> dict:
    """Weekly series, totals and the by-category breakdown for the Mondays start..end."""
    params = {"s": start, "e": end, "e_lots": end + timedelta(days=6)}
    weekly = {w: {
        "week_start": w, "lbs_distributed": 0.0, "households_served": 0, "pantry_weeks": 0,
        "shortage_reports": 0, "pantry_weeks_with_shortage": 0, "received_perishable_lbs": 0.0,
        "expired_perishable_lbs": 0.0,
    } for w in weeks_between(start, end)}  # fmt: skip

    for week, lbs, households, pantry_weeks in db.execute(
        text(
            """
            WITH pw AS (
                SELECT pantry_id, week_start, MAX(households) AS hh, SUM(lbs) AS lbs
                FROM distributions WHERE week_start BETWEEN :s AND :e GROUP BY 1, 2)
            SELECT week_start, SUM(lbs)::float8, SUM(hh)::int, COUNT(*) FROM pw GROUP BY week_start
            """
        ),
        params,
    ):
        weekly[week].update(
            lbs_distributed=lbs, households_served=households, pantry_weeks=pantry_weeks
        )

    for week, reports, with_shortage in db.execute(
        text(
            """
            SELECT r.week_start, COUNT(*),
                   COUNT(DISTINCT r.pantry_id) FILTER (WHERE EXISTS (
                       SELECT 1 FROM distributions d
                       WHERE d.pantry_id = r.pantry_id AND d.week_start = r.week_start))
            FROM shortage_reports r WHERE r.week_start BETWEEN :s AND :e GROUP BY r.week_start
            """
        ),
        params,
    ):
        weekly[week].update(shortage_reports=reports, pantry_weeks_with_shortage=with_shortage)

    for week, received, expired in db.execute(
        text(
            """
            SELECT date_trunc('week', l.received_date)::date, SUM(l.received_lbs)::float8,
                   SUM(l.expired_lbs)::float8
            FROM inventory_lots l JOIN categories c ON c.id = l.category_id
            WHERE c.perishable AND l.received_date BETWEEN :s AND :e_lots GROUP BY 1
            """
        ),
        params,
    ):
        if week in weekly:
            weekly[week].update(received_perishable_lbs=received, expired_perishable_lbs=expired)

    by_category = {
        name: {"category": name, "lbs_distributed": 0.0, "shortage_reports": 0,
               "received_lbs": 0.0, "expired_lbs": 0.0, "perishable": False}
        for name in CATEGORY_NAMES
    }  # fmt: skip
    for name, lbs in db.execute(
        text(
            "SELECT c.name, SUM(d.lbs)::float8 FROM distributions d JOIN categories c "
            "ON c.id = d.category_id WHERE d.week_start BETWEEN :s AND :e GROUP BY c.name"
        ),
        params,
    ):
        by_category[name]["lbs_distributed"] = lbs
    for name, reports in db.execute(
        text(
            "SELECT c.name, COUNT(*) FROM shortage_reports r JOIN categories c "
            "ON c.id = r.category_id WHERE r.week_start BETWEEN :s AND :e GROUP BY c.name"
        ),
        params,
    ):
        by_category[name]["shortage_reports"] = reports
    for name, perishable, received, expired in db.execute(
        text(
            "SELECT c.name, c.perishable, COALESCE(SUM(l.received_lbs), 0)::float8, "
            "COALESCE(SUM(l.expired_lbs), 0)::float8 FROM categories c LEFT JOIN inventory_lots l "
            "ON l.category_id = c.id AND l.received_date BETWEEN :s AND :e_lots GROUP BY c.name, "
            "c.perishable"
        ),
        params,
    ):
        by_category[name].update(perishable=perishable, received_lbs=received, expired_lbs=expired)

    week_rows = []
    for w in weekly.values():
        week_rows.append(
            {
                **w,
                "lbs_distributed": round(w["lbs_distributed"], 2),
                "stockout_pct": _pct(w["pantry_weeks_with_shortage"], w["pantry_weeks"]),
                "spoilage_pct": _pct(w["expired_perishable_lbs"], w["received_perishable_lbs"]),
            }
        )
    cat_rows = [
        {
            "category": c["category"],
            "lbs_distributed": round(c["lbs_distributed"], 2),
            "shortage_reports": c["shortage_reports"],
            "spoilage_pct": _pct(c["expired_lbs"], c["received_lbs"]) if c["perishable"] else None,
        }
        for c in by_category.values()
    ]

    def total(key: str) -> float:
        return sum(w[key] for w in week_rows)

    pantry_weeks = int(total("pantry_weeks"))
    with_shortage = int(total("pantry_weeks_with_shortage"))
    received = total("received_perishable_lbs")
    expired = total("expired_perishable_lbs")
    totals = {
        "lbs_distributed": round(total("lbs_distributed"), 2),
        "households_served": int(total("households_served")),
        "shortage_reports": int(total("shortage_reports")),
        "pantry_weeks": pantry_weeks,
        "pantry_weeks_with_shortage": with_shortage,
        "stockout_pct": _pct(with_shortage, pantry_weeks),
        "received_perishable_lbs": round(received, 2),
        "expired_perishable_lbs": round(expired, 2),
        "spoilage_pct": _pct(expired, received),
    }
    return {"totals": totals, "weekly": week_rows, "by_category": cat_rows}
