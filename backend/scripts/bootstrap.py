"""Deploy-time bootstrap.

    python -m scripts.bootstrap migrate   # the web service on every start: migrations only
    python -m scripts.bootstrap all       # one-off task: also seed, backtest, forecast, allocate

Each data step runs only when its own data is missing, so a run that died halfway is finished by the
next one and a database that already has data is left alone. One runner at a time: a Postgres
advisory lock is held while migrating, checking and loading.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from alembic import command
from app.config import ROOT, get_settings
from app.db import make_engine

LOCK_KEY = 5_150_160_016  # any constant; every task that touches the schema or seed data uses it


@dataclass
class Steps:
    seed: Callable[[], None]
    backtest: Callable[[], None]
    refresh: Callable[[], None]


def _lock(conn) -> None:
    conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})


def _unlock(conn) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})


def run_migrations(url) -> None:
    """Alembic upgrade head, one task at a time (the others wait, then find nothing to do)."""
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            _lock(conn)
            try:
                cfg = Config(str(ROOT / "backend" / "alembic.ini"))
                cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
                cfg.attributes["url"] = url
                command.upgrade(cfg, "head")
            finally:
                _unlock(conn)
                conn.commit()
    finally:
        engine.dispose()


def has_users(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT EXISTS (SELECT 1 FROM users)")).scalar_one()


def has_run(engine: Engine, kind: str) -> bool:
    """A completed backtest; or a completed forward forecast that also has an allocation run."""
    sql = "SELECT EXISTS (SELECT 1 FROM forecast_runs WHERE kind = :k AND status = 'completed')"
    if kind != "backtest":
        sql += " AND EXISTS (SELECT 1 FROM allocation_runs)"
    with engine.connect() as conn:
        return conn.execute(text(sql), {"k": kind}).scalar_one()


def bootstrap(engine: Engine, steps: Steps, migrate: Callable[[], None]) -> dict[str, bool]:
    done = {"seed": False, "backtest": False, "refresh": False}
    migrate()  # takes the same lock itself, so it must run before we hold it
    with engine.connect() as conn:
        _lock(conn)
        try:
            if not has_users(engine):
                steps.seed()
                done["seed"] = True
            if not has_run(engine, "backtest"):
                steps.backtest()
                done["backtest"] = True
            if not has_run(engine, "forward"):
                steps.refresh()
                done["refresh"] = True
        finally:
            _unlock(conn)
            conn.commit()
    return done


def _real_steps(engine: Engine) -> Steps:
    from app.ai.llm_provider import BedrockProvider
    from app.services import forecast_runs
    from app.services import forecasting as fc
    from app.storage import make_storage
    from scripts import seed

    settings = get_settings()
    storage = make_storage(settings)

    def do_seed() -> None:
        passwords = seed.require_demo_passwords(settings)
        seed.assert_safe_target(engine, settings)
        from scripts.generate_synthetic_data import DEFAULT_SEED, generate

        data = seed.add_current_inventory(generate(DEFAULT_SEED))
        seed.load(engine, data, passwords)

    def do_backtest() -> None:
        with Session(engine) as db:
            panel = forecast_runs.load_panel(db)
            result = fc.run_backtest(panel, fc.ForecastConfig(), 12)
            forecast_runs.save_backtest(db, storage, result, panel)

    def do_refresh() -> None:
        from app.jobs.weekly_refresh import run_weekly_refresh

        with Session(engine) as db:
            admin = db.execute(
                text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
            ).scalar_one()
            run_weekly_refresh(
                db,
                storage=storage,
                forecast_config=fc.ForecastConfig(),
                llm=BedrockProvider(settings),
                user_id=admin,
                today=date.today(),
            )

    return Steps(seed=do_seed, backtest=do_backtest, refresh=do_refresh)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("migrate", "all"):
        print("usage: python -m scripts.bootstrap migrate|all", file=sys.stderr)
        return 2
    settings = get_settings()
    if args[0] == "migrate":
        run_migrations(settings.database_url)
        return 0
    engine = make_engine(settings.database_url)
    try:
        started = time.monotonic()
        done = bootstrap(
            engine, _real_steps(engine), migrate=lambda: run_migrations(settings.database_url)
        )
        print(f"bootstrap finished in {time.monotonic() - started:.0f}s: {done}", flush=True)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
