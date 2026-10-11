"""The API for end-to-end tests (`make e2e`). NOT part of the app.

It is the real application wired to the TEST database, a mock LLM, a temporary upload folder and a
pinned date, plus a few `/__e2e/*` routes to reset data and switch the mock AI's behaviour.
It refuses to start unless E2E_MODE=1 is set (the Makefile does this) and the database is the test
database. The normal app (`app.main:create_app`) never imports this file.

    uvicorn scripts.e2e_server:build_app --factory --port 8101
"""

from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text

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
    "TRUNCATE allocation_edits, allocations, allocation_runs, monthly_summaries, login_throttle "
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
    app = create_app(
        settings, engine, llm=llm, storage=LocalStorage(Path(UPLOAD_DIR)), forecast_config=FAST
    )
    app.state.today = lambda: today

    @app.post("/__e2e/reset", status_code=204)
    def reset() -> None:
        with engine.begin() as conn:
            for statement in RESET_SQL:
                conn.execute(text(statement))
        llm.set_mode("ok")
        llm.calls.clear()

    @app.post("/__e2e/llm", status_code=204)
    def set_llm(body: ModeIn) -> None:
        if body.mode not in MODES:
            raise ValueError(body.mode)
        llm.set_mode(body.mode)

    @app.get("/__e2e/state")
    def state() -> dict:
        return {"today": today.isoformat(), "llm_mode": llm.mode, "llm_calls": llm.calls,
                "database": engine.url.database}  # fmt: skip

    return app
