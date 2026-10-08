import pytest
from sqlalchemy import text

from app.auth.passwords import verify_password
from app.config import Settings
from scripts.generate_synthetic_data import DEFAULT_SEED, generate
from scripts.seed import (
    DEMO_EMAILS,
    assert_safe_target,
    load,
    require_demo_passwords,
    truncate_app_tables,
)

PASSWORDS = {"coordinator": "pw-coord-1", "admin": "pw-admin-1", "pantry_manager": "pw-mgr-1"}


@pytest.fixture(scope="module")
def seeded(migrated_engine):
    data = generate(DEFAULT_SEED)
    load(migrated_engine, data, PASSWORDS)
    yield data
    truncate_app_tables(migrated_engine)


def scalar(engine, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def test_row_counts_match_the_generated_data(migrated_engine, seeded):
    expected = {
        "pantries": 85,
        "categories": 8,
        "weekly_context": 6 * 156,
        "distributions": 85 * 8 * 156,
        "shortage_reports": len(seeded.shortage_reports),
        "inventory_lots": len(seeded.inventory_lots),
        "donation_items": len(seeded.donation_items),
        "donations": len(seeded.donations),
        "donors": len(seeded.donors),
        "users": 3,
    }
    for table, count in expected.items():
        assert scalar(migrated_engine, f"SELECT count(*) FROM {table}") == count, table


def test_three_demo_users_with_the_right_roles_and_pantry(migrated_engine, seeded):
    with migrated_engine.connect() as conn:
        rows = conn.execute(text("SELECT email, role, pantry_id FROM users")).all()
    by_role = {role: (email, pantry_id) for email, role, pantry_id in rows}
    assert set(by_role) == {"coordinator", "admin", "pantry_manager"}
    assert by_role["pantry_manager"][1] == 14
    assert by_role["coordinator"][1] is None and by_role["admin"][1] is None
    for role, (email, _) in by_role.items():
        assert email == DEMO_EMAILS[role]


def test_demo_passwords_are_stored_hashed_and_verify(migrated_engine, seeded):
    with migrated_engine.connect() as conn:
        rows = conn.execute(text("SELECT role, password_hash FROM users")).all()
    for role, password_hash in rows:
        assert PASSWORDS[role] not in password_hash
        assert verify_password(PASSWORDS[role], password_hash)
        assert not verify_password("wrong-password", password_hash)


def test_pantry_manager_belongs_to_pantry_14(migrated_engine, seeded):
    name = scalar(
        migrated_engine,
        "SELECT p.name FROM users u JOIN pantries p ON p.id = u.pantry_id "
        "WHERE u.role = 'pantry_manager'",
    )
    assert name == "Pantry 14"


def test_seeded_spoilage_and_stockout_rates_are_in_range(migrated_engine, seeded):
    spoilage = scalar(
        migrated_engine,
        "SELECT sum(l.expired_lbs) / sum(l.received_lbs) FROM inventory_lots l "
        "JOIN categories c ON c.id = l.category_id WHERE c.perishable",
    )
    assert 0.105 <= float(spoilage) <= 0.135
    stockout = scalar(
        migrated_engine,
        "SELECT count(DISTINCT (pantry_id, week_start))::float / (85 * 156) FROM shortage_reports",
    )
    assert 0.20 <= stockout <= 0.30


def test_new_rows_get_ids_after_the_seeded_ones(migrated_engine, seeded):
    """Sequences were reset after loading explicit ids."""
    with migrated_engine.begin() as conn:
        new_id = conn.execute(
            text(
                "INSERT INTO donors (name, donor_type) VALUES ('Brand New Donor', 'other') "
                "RETURNING id"
            )
        ).scalar_one()
        conn.rollback()
    assert new_id > len(seeded.donors)


def test_seeding_twice_gives_the_same_row_counts(migrated_engine, seeded):
    before = scalar(migrated_engine, "SELECT count(*) FROM distributions")
    load(migrated_engine, seeded, PASSWORDS)
    assert scalar(migrated_engine, "SELECT count(*) FROM distributions") == before
    assert scalar(migrated_engine, "SELECT count(*) FROM users") == 3


def test_categories_survive_a_truncate(migrated_engine, seeded):
    truncate_app_tables(migrated_engine)
    assert scalar(migrated_engine, "SELECT count(*) FROM categories") == 8
    assert scalar(migrated_engine, "SELECT count(*) FROM distributions") == 0
    load(migrated_engine, seeded, PASSWORDS)  # leave the module fixture's data in place


def test_seed_refuses_to_run_against_the_test_database(migrated_engine, settings):
    with pytest.raises(SystemExit) as exc:
        assert_safe_target(migrated_engine, settings)
    assert "pantrypulse_test" in str(exc.value) or settings.postgres_test_db in str(exc.value)


def test_seed_accepts_the_configured_app_database(settings):
    from app.db import make_engine

    engine = make_engine(settings.database_url)
    try:
        assert_safe_target(engine, settings)
    finally:
        engine.dispose()


def test_missing_demo_passwords_fail_with_a_clear_message(settings):
    blank = settings.model_copy(
        update={
            "demo_coordinator_password": None,
            "demo_admin_password": "",
            "demo_pantry_manager_password": None,
        }
    )
    with pytest.raises(SystemExit) as exc:
        require_demo_passwords(blank)
    message = str(exc.value)
    for name in (
        "DEMO_COORDINATOR_PASSWORD",
        "DEMO_ADMIN_PASSWORD",
        "DEMO_PANTRY_MANAGER_PASSWORD",
    ):
        assert name in message
    assert ".env" in message


def test_demo_passwords_are_read_when_present(settings):
    filled = settings.model_copy(
        update={
            "demo_coordinator_password": "a",
            "demo_admin_password": "b",
            "demo_pantry_manager_password": "c",
        }
    )
    assert require_demo_passwords(filled) == {
        "coordinator": "a",
        "admin": "b",
        "pantry_manager": "c",
    }


def test_settings_has_no_built_in_demo_passwords():
    assert Settings.model_fields["demo_admin_password"].default is None
