from fastapi.testclient import TestClient
from sqlalchemy.engine import URL

from app.config import Settings
from app.db import make_engine
from app.main import create_app


def test_health_ok_when_database_is_up(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_error_envelope_when_database_is_down(settings: Settings):
    dead_url = URL.create(
        "postgresql+psycopg",
        username="nobody",
        password="nothing",
        host="127.0.0.1",
        port=1,  # nothing listens here
        database="none",
    )
    engine = make_engine(dead_url)
    app = create_app(settings, engine)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "database_unavailable"
    assert error["message"]
    assert "details" in error
    assert "nothing" not in response.text  # no credentials leak into the response
