from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from alembic import command
from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "users", "pantries", "categories", "donors", "donations", "donation_items",
    "inventory_lots", "distributions", "shortage_reports", "weekly_context", "forecast_runs",
    "forecasts", "allocation_runs", "allocations", "allocation_edits", "monthly_summaries",
}  # fmt: skip


def app_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_migration_creates_every_table(migrated_engine):
    assert app_tables(migrated_engine) == EXPECTED_TABLES


def test_models_and_migration_have_not_drifted(migrated_engine, settings):
    # Raises if autogenerate would produce a new migration, i.e. models != migrations.
    command.check(alembic_config(settings.test_database_url))


def test_there_is_a_single_migration_head(settings):
    script = ScriptDirectory.from_config(alembic_config(settings.test_database_url))
    assert len(script.get_heads()) == 1


def test_downgrade_removes_everything_and_upgrade_restores_it(migrated_engine, settings):
    cfg = alembic_config(settings.test_database_url)
    try:
        command.downgrade(cfg, "base")
        assert app_tables(migrated_engine) == set()
    finally:
        command.upgrade(cfg, "head")
    assert app_tables(migrated_engine) == EXPECTED_TABLES
