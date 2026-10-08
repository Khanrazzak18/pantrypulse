"""The committed OpenAPI file is what the frontend's generated types come from."""

import json

from scripts.export_openapi import OPENAPI_PATH, build_openapi


def test_committed_openapi_matches_the_running_api():
    committed = json.loads(OPENAPI_PATH.read_text())
    assert committed == build_openapi(), "API changed: run `make api-types` and commit the result"


def test_openapi_describes_the_auth_and_pantry_routes():
    paths = build_openapi()["paths"]
    assert {"/api/auth/login", "/api/auth/logout", "/api/auth/me"} <= set(paths)
    assert {"/api/pantries", "/api/pantries/{pantry_id}"} <= set(paths)
