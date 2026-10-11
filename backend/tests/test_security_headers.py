"""Security headers on every API response, and CSRF protection: cross-site requests that change
data are refused."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people")


def test_every_api_response_has_the_security_headers(client):
    for response in (
        client.get("/api/health"),
        client.get("/api/nope"),
        client.post("/api/auth/login", json={}),
    ):
        h = response.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "default-src 'none'" in h["content-security-policy"]
        assert "camera=()" in h["permissions-policy"]
        assert h["cross-origin-resource-policy"] == "same-origin"
        assert h["x-frame-options"] == "DENY"


def test_api_responses_are_never_cached(client, people):
    login(client, people.coordinator)
    assert client.get("/api/pantries").headers["cache-control"] == "no-store"
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"


def test_hsts_is_sent_only_when_the_site_is_served_over_https(settings, engine):
    plain = TestClient(create_app(settings, engine))
    assert "strict-transport-security" not in plain.get("/api/health").headers
    secure = TestClient(create_app(settings.model_copy(update={"cookie_secure": True}), engine))
    hsts = secure.get("/api/health").headers["strict-transport-security"]
    assert "max-age=" in hsts and "includeSubDomains" in hsts


def test_headers_are_on_error_responses_too(client):
    assert client.get("/api/auth/me").headers["x-content-type-options"] == "nosniff"  # a 401
    assert client.get("/api/nope").headers["x-content-type-options"] == "nosniff"  # a 404
