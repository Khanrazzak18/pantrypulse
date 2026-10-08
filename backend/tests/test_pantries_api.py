import pytest

from tests.conftest import PANTRY_A, PANTRY_B, login

PANTRY_FIELDS = {
    "id", "name", "county", "latitude", "longitude", "cold_capacity_lbs", "dry_capacity_lbs",
    "baseline_households",
}  # fmt: skip


def error_code(response) -> str:
    return response.json()["error"]["code"]


# --- pantry manager: allowed only their own pantry --------------------------------------------


def test_pantry_manager_calling_a_coordinator_route_gets_403(client, people):
    login(client, people.manager)
    response = client.get("/api/pantries")
    assert response.status_code == 403
    assert error_code(response) == "forbidden"


def test_pantry_manager_can_read_their_own_pantry(client, people):
    login(client, people.manager)
    response = client.get(f"/api/pantries/{PANTRY_A}")
    assert response.status_code == 200
    assert set(response.json()) == PANTRY_FIELDS
    assert response.json()["name"] == "Auth Pantry A"


def test_pantry_manager_reading_another_pantry_gets_403(client, people):
    login(client, people.manager)
    response = client.get(f"/api/pantries/{PANTRY_B}")
    assert response.status_code == 403
    assert error_code(response) == "forbidden"


def test_pantry_manager_gets_403_not_404_for_an_id_that_does_not_exist(client, people):
    """A 404 here would reveal which pantry ids exist."""
    login(client, people.manager)
    assert client.get("/api/pantries/424242").status_code == 403


# --- coordinator and admin ---------------------------------------------------------------------


@pytest.mark.parametrize("role", ["coordinator", "admin"])
def test_coordinator_and_admin_can_list_pantries(client, people, role):
    login(client, getattr(people, role))
    response = client.get("/api/pantries")
    assert response.status_code == 200
    rows = response.json()
    ids = [row["id"] for row in rows]
    assert ids == sorted(ids)
    assert {PANTRY_A, PANTRY_B} <= set(ids)
    assert all(set(row) == PANTRY_FIELDS for row in rows)


@pytest.mark.parametrize("role", ["coordinator", "admin"])
def test_coordinator_and_admin_can_read_any_pantry(client, people, role):
    login(client, getattr(people, role))
    assert client.get(f"/api/pantries/{PANTRY_A}").status_code == 200
    assert client.get(f"/api/pantries/{PANTRY_B}").json()["name"] == "Auth Pantry B"


@pytest.mark.parametrize("role", ["coordinator", "admin"])
def test_an_unknown_pantry_id_is_a_404_for_staff(client, people, role):
    login(client, getattr(people, role))
    response = client.get("/api/pantries/424242")
    assert response.status_code == 404
    assert error_code(response) == "not_found"


def test_a_non_numeric_pantry_id_is_a_422_envelope(client, people):
    login(client, people.coordinator)
    response = client.get("/api/pantries/abc")
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_pantry_coordinates_are_numbers(client, people):
    login(client, people.coordinator)
    pantry = client.get(f"/api/pantries/{PANTRY_A}").json()
    assert isinstance(pantry["latitude"], float) and isinstance(pantry["longitude"], float)
