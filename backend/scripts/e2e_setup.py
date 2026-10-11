"""Prepare the TEST database for `make e2e`: migrate from scratch, load the seed and the backtest.

Run it before the e2e server starts. It only ever touches the database named POSTGRES_TEST_DB.
`make test` (pytest) uses the same database, so run `make test` and `make e2e` one after the other,
never together.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy.orm import Session

from alembic import command
from app.config import ROOT, Settings
from app.db import make_engine
from app.services import forecast_runs
from app.services import forecasting as fc
from app.storage import LocalStorage
from scripts.generate_synthetic_data import DEFAULT_SEED, add_current_inventory, generate
from scripts.seed import load, require_demo_passwords

FAST = fc.ForecastConfig(
    n_estimators=15, num_leaves=7, min_data_in_leaf=5, num_threads=2, min_history_weeks=30
)


def main() -> None:
    settings = Settings()
    if not settings.postgres_test_db.endswith("_test"):
        raise SystemExit("Refusing to run: the test database name must end in _test.")
    url = settings.test_database_url
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend/alembic"))
    cfg.attributes["url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    try:
        load(
            engine, add_current_inventory(generate(DEFAULT_SEED)), require_demo_passwords(settings)
        )
        storage = LocalStorage(Path(ROOT / "backend/var/e2e-uploads"))
        with Session(engine) as db:  # a quick backtest so the Forecasts page has accuracy figures
            panel = forecast_runs.load_panel(db)
            result = fc.run_backtest(panel, FAST, 12)
            forecast_runs.save_backtest(db, storage, result, panel)
    finally:
        engine.dispose()
    print(f"E2E database '{settings.postgres_test_db}' is ready.")


if __name__ == "__main__":
    main()
