from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import PANTRY_A, login

COOKIE = "pp_session"


def test_me_without_a_session_returns_401(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("path", ["/api/pantries", f"/api/pantries/{PANTRY_A}"])
def test_protected_routes_return_401_when_logged_out(client, people, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_returns_the_logged_in_user(client, people):
    login(client, people.admin)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == people.admin
    assert response.json()["role"] == "admin"


def test_logout_clears_the_cookie_and_ends_the_session(client, people):
    login(client, people.coordinator)
    assert client.get("/api/auth/me").status_code == 200
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    cleared = response.headers["set-cookie"]
    assert cleared.startswith(f"{COOKIE}=") and (
        "Max-Age=0" in cleared or "expires" in cleared.lower()
    )
    assert "HttpOnly" in cleared
    assert client.get("/api/auth/me").status_code == 401


def test_logout_when_not_logged_in_is_harmless(client):
    assert client.post("/api/auth/logout").status_code == 204


def test_a_garbage_cookie_returns_401(client, people):
    client.cookies.set(COOKIE, "this-is-not-a-jwt")
    assert client.get("/api/auth/me").status_code == 401


def test_an_expired_token_returns_401(client, people, settings, migrated_engine):
    from app.auth.tokens import create_token

    with migrated_engine.connect() as conn:
        user_id = conn.execute(
            text("SELECT id FROM users WHERE email = :e"), {"e": people.coordinator}
        ).scalar_one()
    long_ago = datetime.now(UTC) - timedelta(hours=9)
    client.cookies.set(COOKIE, create_token(user_id, settings.jwt_secret, 8, now=long_ago))
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_a_user_deactivated_after_login_is_locked_out_immediately(client, people, migrated_engine):
    login(client, people.coordinator)
    assert client.get("/api/auth/me").status_code == 200
    with migrated_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET is_active = false WHERE email = :e"), {"e": people.coordinator}
        )
    assert client.get("/api/auth/me").status_code == 401


def test_a_deleted_user_with_a_valid_token_gets_401(client, people, migrated_engine):
    login(client, people.coordinator)
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": people.coordinator})
    assert client.get("/api/auth/me").status_code == 401


def test_role_changes_in_the_database_apply_on_the_next_request(client, people, migrated_engine):
    """The token carries no role; it is read from the database each time."""
    login(client, people.coordinator)
    assert client.get("/api/pantries").status_code == 200
    with migrated_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET role = 'pantry_manager', pantry_id = :p WHERE email = :e"),
            {"p": PANTRY_A, "e": people.coordinator},
        )
    assert client.get("/api/pantries").status_code == 403
