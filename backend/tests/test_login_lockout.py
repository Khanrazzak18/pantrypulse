"""Login lockout: a database-backed counter of failed attempts per email and per address."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people")


@pytest.fixture(autouse=True)
def clean(migrated_engine):
    wipe = "TRUNCATE login_throttle"
    with migrated_engine.begin() as conn:
        conn.execute(text(wipe))
    yield
    with migrated_engine.begin() as conn:
        conn.execute(text(wipe))


def bad(client, email, password="wrong-password"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT key_hash, failures, locked_until FROM login_throttle")
        ).all()


def test_four_failures_do_not_lock_and_a_good_login_still_works(client, people):
    for _ in range(4):
        assert bad(client, people.coordinator).status_code == 401
    assert login(client, people.coordinator).status_code == 200


def test_the_fifth_failure_locks_even_for_the_right_password(client, people):
    for _ in range(5):
        assert bad(client, people.coordinator).status_code == 401
    response = login(client, people.coordinator)
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "too_many_attempts"
    assert "15 minutes" in error["message"]
    assert int(response.headers["retry-after"]) > 0
    assert "pp_session" not in response.headers.get("set-cookie", "")


def test_an_unknown_email_locks_the_same_way_so_nothing_is_revealed(client):
    for _ in range(5):
        bad(client, "nobody@example.org")
    assert bad(client, "nobody@example.org").status_code == 429


def test_other_emails_are_not_locked(client, people):
    for _ in range(5):
        bad(client, people.coordinator)
    assert login(client, people.admin).status_code == 200


def test_a_success_resets_the_counter(client, people):
    for _ in range(3):
        bad(client, people.coordinator)
    assert login(client, people.coordinator).status_code == 200
    for _ in range(4):
        assert bad(client, people.coordinator).status_code == 401  # would be locked if not reset


def test_the_lock_expires(client, people, engine):
    for _ in range(5):
        bad(client, people.coordinator)
    assert login(client, people.coordinator).status_code == 429
    with engine.begin() as conn:
        conn.execute(text("UPDATE login_throttle SET locked_until = now() - interval '1 second'"))
    assert login(client, people.coordinator).status_code == 200


def test_old_failures_age_out_of_the_window(client, people, engine):
    for _ in range(4):
        bad(client, people.coordinator)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE login_throttle SET first_failure_at = now() - interval '20 minutes'")
        )
    assert bad(client, people.coordinator).status_code == 401  # counts as the first again
    assert bad(client, people.coordinator).status_code == 401
    assert login(client, people.coordinator).status_code == 200


def test_an_inactive_user_counts_as_a_failure(client, people):
    for _ in range(5):
        assert login(client, people.inactive).status_code == 401
    assert login(client, people.inactive).status_code == 429


def test_one_address_trying_many_emails_gets_locked(client, people):
    for i in range(20):
        bad(client, f"person{i}@example.org")
    assert login(client, people.coordinator).status_code == 429


def test_the_counter_lives_in_the_database_not_in_memory(settings, engine, people):
    first = TestClient(create_app(settings, engine))
    for _ in range(5):
        bad(first, people.coordinator)
    second = TestClient(create_app(settings, engine))  # a different "instance"
    assert login(second, people.coordinator).status_code == 429


def test_the_table_stores_hashes_not_emails(client, people, engine):
    bad(client, people.coordinator)
    stored = rows(engine)
    assert stored and all(len(k) == 64 for k, _, _ in stored)
    assert people.coordinator not in " ".join(k for k, _, _ in stored)


def test_a_locked_attempt_does_not_extend_the_lock(client, people, engine):
    for _ in range(5):
        bad(client, people.coordinator)
    before = max(r[2] for r in rows(engine) if r[2])
    for _ in range(3):
        assert login(client, people.coordinator).status_code == 429
    assert max(r[2] for r in rows(engine) if r[2]) == before
    assert before > datetime.now(UTC) + timedelta(minutes=14)
