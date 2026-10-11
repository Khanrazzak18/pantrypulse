"""A request that changes data must come from our own site. Browsers always say where a request
came from (Origin and Sec-Fetch-Site), so a form on another site that the visitor's browser submits
with their cookie is refused. Tools without those headers (curl, the tests) are not browsers and
pass."""

import pytest

from app.config import Settings
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.usefixtures("people")
PORT = Settings().web_port


@pytest.fixture
def me(client, people):
    login(client, people.coordinator)
    return client


def refused(response):
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"


def test_a_post_from_another_site_is_refused(me):
    refused(
        me.post(
            "/api/allocations/bulk-approve",
            json={"ids": [1]},
            headers={"Origin": "https://evil.example"},
        )
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_method_that_changes_data_is_checked(me, method):
    refused(
        me.request(
            method,
            "/api/allocations/bulk-approve",
            json={},
            headers={"Origin": "https://evil.example"},
        )
    )


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_the_browsers_own_fetch_metadata_is_honoured(me, site):
    refused(
        me.post(
            "/api/allocations/bulk-approve", json={"ids": [1]}, headers={"Sec-Fetch-Site": site}
        )
    )


def test_login_is_protected_too(client, people):
    refused(
        client.post(
            "/api/auth/login",
            json={"email": people.coordinator, "password": PASSWORD},
            headers={"Origin": "https://evil.example"},
        )
    )


def test_a_lookalike_origin_is_refused(me):
    for origin in (
        f"http://localhost:{PORT}.evil.example",
        f"http://localhost:{PORT + 1}",
        "null",
        "http://localhost",
    ):
        refused(
            me.post("/api/allocations/bulk-approve", json={"ids": [1]}, headers={"Origin": origin})
        )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_our_own_site_is_allowed(me, host):
    origin = f"http://{host}:{PORT}"
    response = me.post(
        "/api/allocations/bulk-approve",
        json={"ids": [1]},
        headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code != 403


def test_requests_without_browser_headers_are_allowed(me):
    assert me.post("/api/allocations/bulk-approve", json={"ids": [1]}).status_code != 403


def test_reading_data_is_never_blocked_by_the_origin_rule(me):
    assert me.get("/api/pantries", headers={"Origin": "https://evil.example"}).status_code == 200


def test_the_refusal_happens_before_anything_is_changed(me, engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM allocation_edits")).scalar()
    me.post(
        "/api/allocations/bulk-approve",
        json={"ids": [1]},
        headers={"Origin": "https://evil.example"},
    )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM allocation_edits")).scalar() == before


def test_extra_origins_can_be_allowed_in_settings(settings, engine, people):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(
        settings.model_copy(update={"allowed_origins": "https://pantrypulse.example"}), engine
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        login(c, people.coordinator)
        ok = c.post(
            "/api/allocations/bulk-approve",
            json={"ids": [1]},
            headers={"Origin": "https://pantrypulse.example"},
        )
        assert ok.status_code != 403
        refused(
            c.post(
                "/api/allocations/bulk-approve",
                json={"ids": [1]},
                headers={"Origin": "http://localhost:3000"},
            )
        )
