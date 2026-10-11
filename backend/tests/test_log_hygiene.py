"""Logs keep the detail needed to debug (request id, route, status, error type) but never passwords,
session tokens, password hashes, manifest contents or the values of database parameters."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from tests.conftest import PASSWORD, login
from tests.fakes import extraction, item

pytestmark = pytest.mark.usefixtures("people")
MANIFEST_MARKER = "MANIFEST-CONTENT-MARKER-48151623"
NOTE_MARKER = "NOTE-MARKER-77712345"
WRONG_PASSWORD = "wrong-password-MARKER-55512345"


def logs(capsys) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_login_logout_and_failures_never_log_credentials_or_tokens(capsys, client, people):
    login(client, people.coordinator, WRONG_PASSWORD)
    login(client, people.coordinator)
    token = client.cookies.get("pp_session")
    client.get("/api/auth/me")
    client.post("/api/auth/logout")
    seen = logs(capsys)
    assert "login_failed" in seen and "login_succeeded" in seen  # the events are logged...
    for secret in (WRONG_PASSWORD, PASSWORD, token, people.coordinator, "argon2"):
        assert secret not in seen  # ...without the secrets


def test_an_uploaded_manifests_text_is_never_logged(capsys, client, people):
    login(client, people.coordinator)
    client.app.state.llm.script(extraction(items=[item(name="Distinctive Item Name")]))
    body = f"Please accept 10 cases. {MANIFEST_MARKER}".encode()
    response = client.post("/api/donations", files={"file": ("m.txt", body, "text/plain")})
    assert response.status_code == 201
    seen = logs(capsys)
    assert "donation_extracted" in seen
    assert MANIFEST_MARKER not in seen and "Distinctive Item Name" not in seen


def test_notes_and_summaries_are_not_logged(capsys, client, people):
    login(client, people.manager)
    client.post(
        "/api/pantry/shortage-reports",
        json={"category": "dairy", "severity": 1, "note": NOTE_MARKER},
    )
    client.cookies.clear()
    login(client, people.admin)
    client.post("/api/dashboard/summaries/2026-09/approve", json={"text": NOTE_MARKER})
    assert NOTE_MARKER not in logs(capsys)


def test_a_database_error_does_not_put_the_values_in_the_log(settings, engine, capsys):
    app = create_app(settings, engine)

    @app.get("/api/boom-db")
    def boom():
        from sqlalchemy.orm import Session

        with Session(engine) as db:
            db.execute(
                text("SELECT CAST(:v AS jsonb)"), {"v": '{"a": "' + NOTE_MARKER + '\\u0000"}'}
            )

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/api/boom-db")
    assert response.status_code == 422  # a refused value is the caller's problem, not a crash
    seen = logs(capsys)
    assert "database_rejected_value" in seen
    assert NOTE_MARKER not in seen  # SQLAlchemy hides parameter values (hide_parameters=True)


def test_an_unexpected_error_logs_the_type_and_trace_but_the_client_gets_neither(
    settings, engine, capsys
):
    app = create_app(settings, engine)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("something internal")

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/api/boom")
    assert "something internal" not in response.text and "Traceback" not in response.text
    assert "something internal" in logs(capsys)


def test_the_engine_hides_parameters(engine):
    assert engine.hide_parameters is True
