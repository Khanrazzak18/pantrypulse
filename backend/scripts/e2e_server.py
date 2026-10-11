"""The API for end-to-end tests (`make e2e`). NOT part of the app.

It is the real application wired to the TEST database, a mock LLM, a temporary upload folder and a
pinned date, plus a few `/__e2e/*` routes to reset data and switch the mock AI's behaviour.
It refuses to start unless E2E_MODE=1 is set (the Makefile does this) and the database is the test
database. The normal app (`app.main:create_app`) never imports this file.

    uvicorn scripts.e2e_server:build_app --factory --port 8101
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from app.config import ROOT, Settings
from app.db import make_engine
from app.main import create_app
from app.storage import LocalStorage
from scripts.e2e_llm import MODES, MockLLM
from scripts.e2e_setup import FAST

UPLOAD_DIR = ROOT / "backend/var/e2e-uploads"
DEFAULT_TODAY = "2026-10-06"  # a Tuesday: the forecast week is the one starting 2026-10-05

# Everything a test can change, undone by /__e2e/reset. Seeded history, pantries, users and the
# backtest are left alone so a reset takes milliseconds.
RESET_SQL = [
    "TRUNCATE allocation_edits, allocations, allocation_runs, monthly_summaries, login_throttle, "
    "rate_limits "
    "RESTART IDENTITY CASCADE",
    "DELETE FROM shortage_reports WHERE reported_by IS NOT NULL",
    # forward forecasts (the seeded backtest is kind 'backtest')
    "DELETE FROM forecasts WHERE forecast_run_id IN "
    "(SELECT id FROM forecast_runs WHERE kind = 'forward')",
    "DELETE FROM forecast_runs WHERE kind = 'forward'",
    # donations made during tests, with their items and lots
    "DELETE FROM inventory_lots WHERE donation_item_id IN (SELECT i.id FROM donation_items i "
    "JOIN donations d ON d.id = i.donation_id WHERE d.original_filename IS DISTINCT FROM "
    "'seeded-current-inventory' AND d.source_type <> 'historical')",
    "DELETE FROM donation_items WHERE donation_id IN (SELECT id FROM donations "
    "WHERE source_type <> 'historical')",
    "DELETE FROM donations WHERE source_type <> 'historical'",
    "DELETE FROM donors WHERE id NOT IN "
    "(SELECT donor_id FROM donations WHERE donor_id IS NOT NULL)",
    # stock on hand goes back to what the seed made
    "UPDATE inventory_lots SET remaining_lbs = received_lbs, status = 'available' "
    "WHERE donation_item_id IN (SELECT i.id FROM donation_items i JOIN donations d "
    "ON d.id = i.donation_id WHERE d.original_filename = 'seeded-current-inventory')",
    "UPDATE users SET is_active = true",
]


class ModeIn(BaseModel):
    mode: str


# Faults a test can switch on: the database is down, every request is slow, or the pantry list is
# empty. They let the E2E tests reach states that are hard to make with real data.
FAULTS = ("none", "db_down", "slow", "empty_pantries", "api_error")
SLOW_SECONDS = 1.5


def guard(settings: Settings) -> None:
    if os.environ.get("E2E_MODE") != "1":
        raise RuntimeError("scripts.e2e_server only runs for end-to-end tests (set E2E_MODE=1).")
    if not settings.postgres_test_db.endswith("_test"):
        raise RuntimeError("The test database name must end in _test.")


def build_app() -> FastAPI:
    settings = Settings()
    guard(settings)
    today = date.fromisoformat(os.environ.get("E2E_TODAY", DEFAULT_TODAY))
    engine = make_engine(settings.test_database_url)  # never the app database
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    llm = MockLLM(today)
    fault = {"mode": "none"}

    @event.listens_for(engine, "engine_connect")
    def _maybe_down(_connection):
        if fault["mode"] == "db_down":
            raise OperationalError("connect", {}, Exception("e2e fault: the database is down"))

    app = create_app(
        settings, engine, llm=llm, storage=LocalStorage(Path(UPLOAD_DIR)), forecast_config=FAST
    )
    app.state.today = lambda: today

    @app.middleware("http")
    async def faults(request: Request, call_next):
        if request.url.path.startswith("/__e2e"):
            return await call_next(request)
        if fault["mode"] == "slow":
            await asyncio.sleep(SLOW_SECONDS)
        listing = request.method == "GET" and request.url.path == "/api/pantries"
        if fault["mode"] == "empty_pantries" and listing:
            return JSONResponse([])
        if fault["mode"] == "api_error" and listing:
            error = {"code": "internal_error", "message": "Something went wrong.", "details": None}
            return JSONResponse({"error": {**error, "request_id": "e2e-fault"}}, status_code=500)
        return await call_next(request)

    @app.post("/__e2e/fault", status_code=204)
    def set_fault(body: ModeIn) -> None:
        if body.mode not in FAULTS:
            raise ValueError(body.mode)
        fault["mode"] = body.mode

    @app.post("/__e2e/reset", status_code=204)
    def reset() -> None:
        fault["mode"] = "none"  # first, or a database fault would block the reset itself
        with engine.begin() as conn:
            for statement in RESET_SQL:
                conn.execute(text(statement))
        llm.set_mode("ok")
        llm.calls.clear()

    @app.post("/__e2e/urgent-lot", status_code=204)
    def urgent_lot() -> None:
        """A confirmed lot of fresh produce that expires two days after the pinned date. The API
        refuses to confirm an expiry that is in the real past, so tests cannot make one that way."""
        expiry = (today + timedelta(days=2)).isoformat()
        with engine.begin() as conn:
            donor = conn.execute(
                text(
                    "INSERT INTO donors (name, donor_type) "
                    "VALUES ('Urgent Foods', 'grocery') RETURNING id"
                )
            ).scalar_one()
            donation = conn.execute(
                text(
                    "INSERT INTO donations (donor_id, source_type, status, received_at) "
                    "VALUES (:d, 'email', 'confirmed', now()) RETURNING id"
                ),
                {"d": donor},
            ).scalar_one()
            category = conn.execute(
                text("SELECT id FROM categories WHERE name = 'produce'")
            ).scalar_one()
            item = conn.execute(
                text(
                    "INSERT INTO donation_items (donation_id, name, category_id, quantity, unit, "
                    "estimated_weight_lbs, expiry_date, storage_type) VALUES "
                    "(:n, 'Fresh spinach', :c, 20, 'case', 900, :e, 'refrigerated') RETURNING id"
                ),
                {"n": donation, "c": category, "e": expiry},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO inventory_lots (donation_item_id, category_id, storage_type, "
                    "received_lbs, remaining_lbs, expired_lbs, received_date, expiry_date, status) "
                    "VALUES "
                    "(:i, :c, 'refrigerated', 900, 900, 0, :r, :e, 'available')"
                ),
                {"i": item, "c": category, "r": today.isoformat(), "e": expiry},
            )

    @app.post("/__e2e/llm", status_code=204)
    def set_llm(body: ModeIn) -> None:
        if body.mode not in MODES:
            raise ValueError(body.mode)
        llm.set_mode(body.mode)

    @app.get("/__e2e/state")
    def state() -> dict:
        return {"today": today.isoformat(), "llm_mode": llm.mode, "llm_calls": llm.calls,
                "fault": fault["mode"], "database": engine.url.database}  # fmt: skip

    return app
