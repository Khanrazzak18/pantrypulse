"""One error envelope, always: outages are 503, bad input is 4xx, nothing is ever a raw 500."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.auth.tokens import create_token
from app.db import make_engine
from app.main import create_app
from tests.conftest import PASSWORD, login

KEYS = {"code", "message", "details", "request_id"}


def assert_envelope(response, status, code=None):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == KEYS
    assert body["error"]["message"]
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    if code:
        assert body["error"]["code"] == code
    return body["error"]


@pytest.fixture
def down_client(settings, people):
    """An API whose database cannot be reached (nothing listens on that port)."""
    url = settings.test_database_url.set(port=1)
    engine = make_engine(url)
    app = create_app(settings, engine)
    secret = settings.jwt_secret
    with Session(make_engine(settings.test_database_url)) as db:
        from app.models import User

        uid = db.query(User).filter_by(email=people.coordinator).one().id
    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set("pp_session", create_token(uid, secret, 8))
        yield c
    engine.dispose()


def test_an_outage_is_a_503_service_unavailable_with_a_retry_hint(down_client):
    error = assert_envelope(down_client.get("/api/auth/me"), 503, "service_unavailable")
    assert "temporarily unavailable" in error["message"].lower()
    assert down_client.get("/api/auth/me").headers["retry-after"]


def test_every_kind_of_request_reports_an_outage_the_same_way(down_client):
    for method, path, body in [
        ("GET", "/api/pantries", None),
        ("GET", "/api/forecasts/series?pantry_id=1&category=produce", None),
        ("POST", "/api/forecasts/run", None),
        ("POST", "/api/auth/login", {"email": "a@b.co", "password": "x"}),
    ]:
        response = down_client.request(method, path, json=body)
        assert_envelope(response, 503, "service_unavailable")


def test_health_says_the_database_is_down(down_client):
    error = assert_envelope(down_client.get("/api/health"), 503, "service_unavailable")
    assert error["details"] == {"database": "down"}


def test_health_is_ok_when_the_database_is_up(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}


def test_an_outage_is_not_a_logout(down_client):
    # the session cookie is valid; the answer must not be 401 (which the web app treats as a logout)
    assert down_client.get("/api/auth/me").status_code == 503


def test_an_unexpected_error_is_a_500_envelope_with_a_request_id_and_no_trace(
    settings, engine, capsys
):
    app = create_app(settings, engine)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret internal detail /Users/someone/file.py")

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/api/boom")
    error = assert_envelope(response, 500, "internal_error")
    assert "secret" not in response.text and "Traceback" not in response.text
    assert error["message"] == "Something went wrong."
    logged = capsys.readouterr().out
    assert (
        "secret internal detail" in logged and '"request_id": "' in logged
    )  # the log keeps the detail


def test_a_database_data_error_is_a_422_not_a_500(settings, engine):
    app = create_app(settings, engine)

    @app.get("/api/bad-data")
    def bad_data():
        raise DataError("stmt", {}, Exception("value out of range"))

    with TestClient(app, raise_server_exceptions=False) as c:
        assert_envelope(c.get("/api/bad-data"), 422, "validation_error")


def test_validation_errors_carry_the_request_id(client):
    assert_envelope(client.post("/api/auth/login", json={}), 422, "validation_error")


def test_unknown_routes_and_methods_carry_the_request_id(client):
    assert_envelope(client.get("/api/nope"), 404)
    assert_envelope(client.delete("/api/health"), 405)


@pytest.mark.usefixtures("people")
class TestControlCharacters:
    def test_login_email_and_password(self, client):
        for body in (
            {"email": "a\u0000b@c.de", "password": "x"},
            {"email": "a@b.co", "password": "a\u0000b"},
            {"email": "a\u0007@b.co", "password": "x"},
        ):
            error = assert_envelope(
                client.post("/api/auth/login", json=body), 422, "validation_error"
            )
            assert "control characters" in str(error["details"])

    def test_a_good_login_still_works(self, client, people):
        assert login(client, people.coordinator).status_code == 200
        assert PASSWORD
