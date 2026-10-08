"""Load the synthetic history and three demo users into the app database.

Run from the backend folder (make seed does this):  python -m scripts.seed

This is destructive for the app database: it truncates every table except `categories` and
`alembic_version`, then reloads. It refuses to run against any database other than POSTGRES_DB.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from app.auth.passwords import hash_password
from app.config import Settings, get_settings
from app.db import make_engine
from app.models import Base
from scripts.generate_synthetic_data import DEFAULT_SEED, generate, summarize

DEMO_EMAILS = {
    "coordinator": "coordinator@harvestbridge.example.org",
    "admin": "admin@harvestbridge.example.org",
    "pantry_manager": "manager14@harvestbridge.example.org",
}
DEMO_NAMES = {
    "coordinator": "Demo Coordinator",
    "admin": "Demo Director",
    "pantry_manager": "Demo Manager (Pantry 14)",
}
DEMO_PASSWORD_VARS = {
    "coordinator": "DEMO_COORDINATOR_PASSWORD",
    "admin": "DEMO_ADMIN_PASSWORD",
    "pantry_manager": "DEMO_PANTRY_MANAGER_PASSWORD",
}
DEMO_PANTRY_ID = 14
KEEP_TABLES = {"categories", "alembic_version"}  # reference data and migration state
INSERT_CHUNK = 5_000


def require_demo_passwords(settings: Settings) -> dict[str, str]:
    """Demo passwords live in .env only. Fail loudly if any is missing."""
    values = {
        "coordinator": settings.demo_coordinator_password,
        "admin": settings.demo_admin_password,
        "pantry_manager": settings.demo_pantry_manager_password,
    }
    missing = [DEMO_PASSWORD_VARS[role] for role, value in values.items() if not value]
    if missing:
        raise SystemExit(
            "make seed needs demo passwords, but these are missing or empty: "
            + ", ".join(missing)
            + ".\nSet them in .env (copy the DEMO_* lines from .env.example), then run "
            "make seed again."
        )
    return {role: value for role, value in values.items() if value}


def assert_safe_target(engine: Engine, settings: Settings) -> None:
    database = engine.url.database
    if database != settings.postgres_db:
        raise SystemExit(
            f"Refusing to seed database '{database}': make seed only touches the app "
            f"database '{settings.postgres_db}'."
        )


def app_tables() -> list[str]:
    return [t.name for t in Base.metadata.sorted_tables if t.name not in KEEP_TABLES]


def truncate_app_tables(engine: Engine) -> None:
    names = ", ".join(app_tables())
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def _insert(conn, table_name: str, rows: list[dict]) -> None:
    table = Base.metadata.tables[table_name]
    for start in range(0, len(rows), INSERT_CHUNK):
        conn.execute(table.insert(), rows[start : start + INSERT_CHUNK])


def _reset_sequence(conn, table_name: str) -> None:
    conn.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT max(id) FROM {table_name}), 1), "
            f"(SELECT count(*) > 0 FROM {table_name}))"
        )
    )


def load(engine: Engine, data, passwords: dict[str, str]) -> None:
    """Replace the app tables' contents with `data` plus the three demo users."""
    truncate_app_tables(engine)
    with engine.begin() as conn:
        for name, rows in data.tables().items():
            _insert(conn, name, rows)
        users = [
            {
                "email": DEMO_EMAILS[role],
                "password_hash": hash_password(passwords[role]),
                "full_name": DEMO_NAMES[role],
                "role": role,
                "pantry_id": DEMO_PANTRY_ID if role == "pantry_manager" else None,
            }
            for role in ("coordinator", "admin", "pantry_manager")
        ]
        _insert(conn, "users", users)
        # Rows were inserted with explicit ids, so move each sequence past them.
        for name in [*data.tables(), "users"]:
            _reset_sequence(conn, name)


def main() -> None:
    settings = get_settings()
    passwords = require_demo_passwords(settings)
    engine = make_engine(settings.database_url)
    try:
        assert_safe_target(engine, settings)
        data = generate(DEFAULT_SEED)
        load(engine, data, passwords)
        with engine.connect() as conn:
            print("\nRow counts:")
            for name in app_tables() + ["categories"]:
                count = conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()
                print(f"  {name:20s} {count:>9,}")
    finally:
        engine.dispose()
    print("\nBaseline (synthetic history):")
    for key, value in summarize(data).items():
        print(f"  {key:28s} {value:6.2f}")
    print("\nDemo logins (local only; passwords are the DEMO_* values in .env):")
    for role, email in DEMO_EMAILS.items():
        extra = f" (Pantry {DEMO_PANTRY_ID})" if role == "pantry_manager" else ""
        print(f"  {role:15s} {email}{extra}")


if __name__ == "__main__":
    main()  # a SystemExit with a message prints it once to stderr and exits with status 1
