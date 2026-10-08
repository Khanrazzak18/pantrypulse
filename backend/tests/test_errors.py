import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from app.errors import ApiError


class Payload(BaseModel):
    quantity: int


@pytest.fixture
def client_with_test_routes(app, client):
    router = APIRouter(prefix="/api/_test")

    @router.post("/validate")
    def validate(payload: Payload):
        return payload

    @router.get("/api-error")
    def api_error():
        raise ApiError(409, "conflict_example", "Already exists.", {"id": 7})

    @router.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    return client


def assert_envelope(body: dict, code: str):
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code


def test_unknown_route_uses_envelope(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert_envelope(response.json(), "not_found")


def test_wrong_method_uses_envelope(client):
    response = client.post("/api/health")
    assert response.status_code == 405
    assert_envelope(response.json(), "method_not_allowed")


def test_validation_error_uses_envelope_with_field_details(client_with_test_routes):
    response = client_with_test_routes.post("/api/_test/validate", json={"quantity": "lots"})
    assert response.status_code == 422
    body = response.json()
    assert_envelope(body, "validation_error")
    assert body["error"]["details"][0]["field"] == "quantity"


def test_api_error_carries_status_code_and_details(client_with_test_routes):
    response = client_with_test_routes.get("/api/_test/api-error")
    assert response.status_code == 409
    body = response.json()
    assert_envelope(body, "conflict_example")
    assert body["error"]["details"] == {"id": 7}


def test_unhandled_exception_returns_500_envelope_without_leaking(client_with_test_routes):
    response = client_with_test_routes.get("/api/_test/boom")
    assert response.status_code == 500
    assert_envelope(response.json(), "internal_error")
    assert "secret internal detail" not in response.text
