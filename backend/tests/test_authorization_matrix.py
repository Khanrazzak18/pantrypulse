"""Every API route, called as every kind of visitor: logged out, pantry manager, coordinator, admin.

The table below says who may use each route. A route that is not in it fails the test, so adding an
endpoint forces a decision about who may call it. "Allowed" means the request gets past the access
check (it may still be a 404 or 422 for the made-up record or input); "denied" means 401 when logged
out and 403 when logged in with the wrong role.
"""

import pytest

from tests.conftest import login
from tests.openapi_helpers import resolve, sample

ANON, MANAGER, COORD, ADMIN = "anon", "manager", "coordinator", "admin"
EVERYONE = {ANON, MANAGER, COORD, ADMIN}
SIGNED_IN = {MANAGER, COORD, ADMIN}
STAFF = {COORD, ADMIN}

ACCESS = {
    ("GET", "/api/health"): EVERYONE,
    ("POST", "/api/auth/login"): EVERYONE,
    ("POST", "/api/auth/logout"): EVERYONE,
    ("GET", "/api/auth/me"): SIGNED_IN,
    ("GET", "/api/pantries"): STAFF,
    ("GET", "/api/pantries/{pantry_id}"): SIGNED_IN,  # a manager only for their own pantry
    ("GET", "/api/donors"): STAFF,
    ("GET", "/api/donations"): STAFF,
    ("POST", "/api/donations"): STAFF,
    ("GET", "/api/donations/{donation_id}"): STAFF,
    ("POST", "/api/donations/{donation_id}/confirm"): STAFF,
    ("POST", "/api/donations/{donation_id}/reject"): STAFF,
    ("POST", "/api/forecasts/run"): STAFF,
    ("GET", "/api/forecasts/runs/latest"): STAFF,
    ("GET", "/api/forecasts"): STAFF,
    ("GET", "/api/forecasts/series"): STAFF,
    ("POST", "/api/allocations/run"): STAFF,
    ("GET", "/api/allocations"): STAFF,
    ("GET", "/api/allocations/runs/latest"): STAFF,
    ("POST", "/api/allocations/runs/{run_id}/reasons"): STAFF,
    ("POST", "/api/allocations/bulk-approve"): STAFF,
    ("POST", "/api/allocations/{allocation_id}/approve"): STAFF,
    ("POST", "/api/allocations/{allocation_id}/edit"): STAFF,
    ("POST", "/api/allocations/{allocation_id}/reject"): STAFF,
    ("GET", "/api/pantry/deliveries"): {MANAGER},
    ("GET", "/api/pantry/shortage-reports"): {MANAGER},
    ("POST", "/api/pantry/shortage-reports"): {MANAGER},
    ("GET", "/api/dashboard/metrics"): {ADMIN},
    ("GET", "/api/dashboard/summaries/{month}"): {ADMIN},
    ("POST", "/api/dashboard/summaries/{month}/draft"): {ADMIN},
    ("POST", "/api/dashboard/summaries/{month}/approve"): {ADMIN},
    ("POST", "/api/admin/jobs/weekly-refresh"): {ADMIN},
}
SLOW = {("POST", "/api/forecasts/run"), ("POST", "/api/admin/jobs/weekly-refresh")}


def routes(client):
    spec = client.app.openapi()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            yield method.upper(), path, op, spec


def build(path, op, spec):
    params = [resolve(p, spec) for p in op.get("parameters", [])]
    url = path
    for p in params:
        if p["in"] == "path":
            url = url.replace("{" + p["name"] + "}", "2026-09" if p["name"] == "month" else "1")
    query = {
        p["name"]: sample(p["schema"], spec)
        for p in params
        if p["in"] == "query" and p.get("required")
    }
    content = op.get("requestBody", {}).get("content", {})
    body = (
        sample(content["application/json"]["schema"], spec)
        if "application/json" in content
        else None
    )
    return url, query, body, "multipart/form-data" in content


def call(client, method, url, query, body, multipart):
    if multipart:
        return client.request(
            method, url, params=query, files={"file": ("a.txt", b"x", "text/plain")}
        )
    return client.request(method, url, params=query, json=body)


def test_every_route_is_in_the_access_table(client):
    found = {(m, p) for m, p, _, _ in routes(client)}
    assert found - set(ACCESS) == set(), "new routes need an entry in ACCESS"
    assert set(ACCESS) - found == set(), "ACCESS lists routes that no longer exist"


@pytest.mark.usefixtures("people")
@pytest.mark.parametrize("role", [ANON, MANAGER, COORD, ADMIN])
def test_each_role_gets_exactly_the_access_it_should(client, people, role):
    if role != ANON:
        email = {MANAGER: people.manager, COORD: people.coordinator, ADMIN: people.admin}[role]
        login(client, email)
    wrong = []
    # logout ends the session, so it goes last
    ordered = sorted(routes(client), key=lambda r: r[1] == "/api/auth/logout")
    for method, path, op, spec in ordered:
        if (method, path) in SLOW:
            continue
        url, query, body, multipart = build(path, op, spec)
        response = call(client, method, url, query, body, multipart)
        allowed = role in ACCESS[(method, path)]
        if allowed:
            if response.status_code in (401, 403) and not (
                role == MANAGER and path == "/api/pantries/{pantry_id}"
            ):
                wrong.append(f"{role} should reach {method} {path} but got {response.status_code}")
        else:
            expected = 401 if role == ANON else 403
            if response.status_code != expected:
                wrong.append(
                    f"{role} on {method} {path}: expected {expected}, got {response.status_code}"
                )
    assert wrong == []


@pytest.mark.usefixtures("people")
def test_slow_routes_are_closed_to_the_wrong_roles_too(client, people):
    for email in (people.manager, people.coordinator):
        client.cookies.clear()
        login(client, email)
        assert client.post("/api/admin/jobs/weekly-refresh").status_code == 403
    client.cookies.clear()
    assert client.post("/api/admin/jobs/weekly-refresh").status_code == 401
    assert client.post("/api/forecasts/run").status_code == 401
    login(client, people.manager)
    assert client.post("/api/forecasts/run").status_code == 403


@pytest.mark.usefixtures("people")
def test_a_manager_reaches_only_their_own_pantry(client, people):
    login(client, people.manager)
    assert client.get("/api/pantries/901").status_code == 200
    assert client.get("/api/pantries/902").status_code == 403
    assert client.get("/api/pantries/999999").status_code == 403  # does not say which ids exist


def test_the_api_documentation_is_not_public_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
