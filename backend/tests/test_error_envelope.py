"""Every API route answers errors in the one envelope {"error": {"code", "message", "details"}},
whoever calls it and however badly."""

import re

import pytest

from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people")


def routes(app):
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            yield method.upper(), path


def fill(path):
    return re.sub(r"\{[^}]+\}", "1", path).replace("/1/", "/1/")


def assert_envelope(response):
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "details"}
    assert isinstance(body["error"]["code"], str) and body["error"]["message"]


def test_every_route_refuses_a_logged_out_caller_in_the_envelope(client, app):
    public = {"/api/health", "/api/auth/login", "/api/auth/logout"}
    checked = 0
    for method, path in routes(app):
        if path in public:
            continue
        response = client.request(method, fill(path), json={} if method != "GET" else None)
        assert response.status_code == 401, (method, path, response.status_code)
        assert_envelope(response)
        checked += 1
    assert checked >= 25


def test_every_route_refuses_the_wrong_role_in_the_envelope(client, people, app):
    login(client, people.manager)
    allowed = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me"}
    manager_routes = {
        "/api/pantry/deliveries",
        "/api/pantry/shortage-reports",
        "/api/pantries/{pantry_id}",
    }
    for method, path in routes(app):
        if path in allowed or path in manager_routes:
            continue
        response = client.request(method, fill(path), json={} if method != "GET" else None)
        assert response.status_code == 403, (method, path, response.status_code)
        assert_envelope(response)


@pytest.mark.parametrize("method, path", [("GET", "/api/nothing-here"), ("DELETE", "/api/health")])
def test_unknown_routes_and_methods_use_the_envelope(client, method, path):
    response = client.request(method, path)
    assert response.status_code in (404, 405)
    assert_envelope(response)


def test_malformed_json_is_a_validation_error_in_the_envelope(client, people):
    login(client, people.admin)
    response = client.post(
        "/api/allocations/bulk-approve",
        content="{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert_envelope(response)


def test_a_missing_record_is_a_404_in_the_envelope(client, people):
    login(client, people.admin)
    for path in ("/api/donations/999999", "/api/pantries/999999"):
        response = client.get(path)
        assert response.status_code == 404
        assert_envelope(response)
