"""Sessions can be revoked: logging out, deactivating a user or changing their role or password
invalidates every token already issued (the `token_version` column), even a copied one."""

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.tokens import create_token, decode_session
from app.main import create_app
from app.models import User
from tests.conftest import login

COOKIE = "pp_session"
pytestmark = pytest.mark.usefixtures("people")


def user_row(engine, email):
    with Session(engine) as db:
        user = db.query(User).filter_by(email=email).one()
        return user.id, user.token_version


def second_client(settings, engine):
    return TestClient(create_app(settings, engine), raise_server_exceptions=False)


def test_a_new_login_token_carries_the_users_current_version(client, people, engine):
    login(client, people.coordinator)
    claims = decode_session(client.cookies.get(COOKIE), client.app.state.settings.jwt_secret)
    assert claims is not None
    assert (claims.user_id, claims.version) == user_row(engine, people.coordinator)


def test_logout_revokes_the_token_even_if_it_was_copied(client, people):
    login(client, people.coordinator)
    copied = client.cookies.get(COOKIE)
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set(COOKIE, copied)  # an attacker replays the copied cookie
    assert client.get("/api/auth/me").status_code == 401


def test_logout_ends_every_session_of_that_user_but_nobody_elses(client, people, settings, engine):
    other_device = second_client(settings, engine)
    login(client, people.coordinator)
    login(other_device, people.coordinator)
    admin_client = second_client(settings, engine)
    login(admin_client, people.admin)
    client.post("/api/auth/logout")
    assert other_device.get("/api/auth/me").status_code == 401
    assert admin_client.get("/api/auth/me").status_code == 200


def test_logging_in_again_after_logout_works(client, people):
    login(client, people.coordinator)
    client.post("/api/auth/logout")
    assert login(client, people.coordinator).status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_logout_with_a_bad_or_missing_cookie_is_harmless(client):
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set(COOKIE, "garbage")
    assert client.post("/api/auth/logout").status_code == 204


@pytest.mark.parametrize(
    "change",
    [
        {"is_active": False},
        {"role": "admin"},
        {"password_hash": "$argon2id$changed"},
    ],
)
def test_changing_a_user_through_the_app_bumps_the_version(client, people, engine, change):
    login(client, people.coordinator)
    copied = client.cookies.get(COOKIE)
    user_id, before = user_row(engine, people.coordinator)
    with Session(engine) as db:
        user = db.get(User, user_id)
        for key, value in change.items():
            setattr(user, key, value)
        db.commit()
    assert user_row(engine, people.coordinator)[1] == before + 1
    client.cookies.set(COOKIE, copied)
    assert client.get("/api/auth/me").status_code == 401  # revoked, not merely re-checked
    with Session(engine) as db:  # put the user back for the other tests
        user = db.get(User, user_id)
        user.is_active, user.role = True, "coordinator"
        db.commit()
    client.cookies.set(COOKIE, copied)
    assert client.get("/api/auth/me").status_code == 401  # reactivating does not revive old tokens


def test_changing_an_unrelated_field_does_not_revoke(client, people, engine):
    login(client, people.coordinator)
    user_id, before = user_row(engine, people.coordinator)
    with Session(engine) as db:
        db.get(User, user_id).full_name = "A New Name"
        db.commit()
    assert user_row(engine, people.coordinator)[1] == before
    assert client.get("/api/auth/me").status_code == 200


def test_a_token_without_a_version_or_with_the_wrong_one_is_refused(
    client, people, settings, engine
):
    user_id, version = user_row(engine, people.coordinator)
    secret = settings.jwt_secret
    old_style = jwt.encode(
        {"sub": str(user_id), "iat": 1_900_000_000, "exp": 4_000_000_000}, secret, algorithm="HS256"
    )
    client.cookies.set(COOKIE, old_style)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE, create_token(user_id, secret, 8, version=version + 1))
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE, create_token(user_id, secret, 8, version=version))
    assert client.get("/api/auth/me").status_code == 200


def test_the_database_column_defaults_to_zero_and_is_not_null(engine):
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'token_version'"
            )
        ).one()
    assert row[0] == "NO" and "0" in row[1]
