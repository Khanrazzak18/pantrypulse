import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.logging import JsonFormatter
from app.main import create_app
from tests.conftest import PASSWORD, login

COOKIE = "pp_session"


def test_login_sets_an_httponly_lax_cookie_and_returns_the_user(client, people):
    response = login(client, people.coordinator)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == people.coordinator
    assert body["role"] == "coordinator"
    assert body["pantry_id"] is None
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=28800" in cookie  # 8 hours
    assert "Secure" not in cookie  # plain http on localhost


def test_login_response_never_contains_the_token_or_the_password_hash(client, people):
    response = login(client, people.coordinator)
    token = client.cookies.get(COOKIE)
    assert token and token not in response.text
    assert "password" not in response.text and "argon2" not in response.text


def test_cookie_is_marked_secure_when_configured(settings, engine, people):
    app = create_app(settings.model_copy(update={"cookie_secure": True}), engine)
    with TestClient(app) as secure_client:
        response = login(secure_client, people.coordinator)
    assert "Secure" in response.headers["set-cookie"]


def test_login_for_a_pantry_manager_includes_their_pantry(client, people):
    body = login(client, people.manager).json()
    assert body["role"] == "pantry_manager"
    assert body["pantry_id"] == 901
    assert body["pantry_name"] == "Auth Pantry A"


def test_wrong_password_returns_401_and_no_cookie(client, people):
    response = login(client, people.coordinator, "not-the-password")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "invalid_credentials"
    assert error["message"] == "Incorrect email or password."
    assert "set-cookie" not in response.headers


def without_id(response):
    """The body minus the per-request id, which is different on every request."""
    error = dict(response.json()["error"])
    error.pop("request_id")
    return error


def test_unknown_email_gets_exactly_the_same_response_as_a_wrong_password(client, people):
    wrong_password = login(client, people.coordinator, "nope")
    unknown_email = login(client, "nobody@example.org", "nope")
    assert unknown_email.status_code == wrong_password.status_code == 401
    assert without_id(unknown_email) == without_id(wrong_password)


def test_inactive_user_cannot_log_in_and_gets_the_same_response(client, people):
    inactive = login(client, people.inactive)
    wrong = login(client, people.coordinator, "nope")
    assert inactive.status_code == 401
    assert without_id(inactive) == without_id(wrong)
    assert "set-cookie" not in inactive.headers


def test_a_password_is_checked_even_for_an_unknown_email(client, people, monkeypatch):
    """So an unknown email costs the same time as a known one (no user enumeration by timing)."""
    import app.api.auth as auth_api

    calls = []
    real = auth_api.verify_password
    monkeypatch.setattr(auth_api, "verify_password", lambda p, h: calls.append(1) or real(p, h))
    login(client, "nobody@example.org", "nope")
    assert len(calls) == 1


def test_email_is_case_insensitive_and_trimmed(client, people):
    response = login(client, f"  {people.coordinator.upper()}  ")
    assert response.status_code == 200
    assert response.json()["email"] == people.coordinator


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email", "password": "x"}, "email"),
        ({"email": "", "password": "x"}, "email"),
        ({"email": "a@example.org", "password": ""}, "password"),
        ({"email": "a@example.org"}, "password"),
        ({"password": "x"}, "email"),
        ({"email": "a@example.org", "password": "x" * 1000}, "password"),
    ],
)
def test_bad_login_bodies_return_a_422_envelope(client, payload, field):
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in [d["field"] for d in error["details"]]


@pytest.fixture
def app_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("pantrypulse")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def entries() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    yield stream, entries
    logger.removeHandler(handler)


def test_successful_login_logs_the_user_id(client, people, app_logs):
    _, entries = app_logs
    login(client, people.coordinator)
    event = next(e for e in entries() if e["message"] == "login_succeeded")
    assert isinstance(event["user_id"], int)
    assert event["request_id"]


def test_logs_never_contain_the_password_or_the_email_of_a_failed_login(client, people, app_logs):
    stream, entries = app_logs
    login(client, "someone.unknown@example.org", "Sup3r-secret-attempt")
    login(client, people.coordinator, "Another-secret-attempt")
    logged = stream.getvalue()
    assert "Sup3r-secret-attempt" not in logged
    assert "Another-secret-attempt" not in logged
    assert "someone.unknown@example.org" not in logged
    failures = [e for e in entries() if e["message"] == "login_failed"]
    assert len(failures) == 2
    assert {f["reason"] for f in failures} == {"unknown_email", "wrong_password"}


def test_the_demo_password_constant_is_not_trivially_short():
    assert len(PASSWORD) >= 12
