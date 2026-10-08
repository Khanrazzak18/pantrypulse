import io
import json
import logging

import pytest

from app.logging import JsonFormatter


@pytest.fixture
def log_lines():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("pantrypulse.request")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def read() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    yield read
    logger.removeHandler(handler)


def test_request_log_line_is_json_with_required_fields(client, log_lines):
    response = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    entry = log_lines()[-1]
    assert entry["message"] == "request"
    assert entry["request_id"] == "abc-123"
    assert entry["method"] == "GET"
    assert entry["route"] == "/api/health"
    assert entry["status"] == 200
    assert isinstance(entry["duration_ms"], (int, float))
    assert entry["level"] == "INFO"
    assert "ts" in entry
    assert response.headers["X-Request-ID"] == "abc-123"


def test_request_id_is_generated_when_missing(client, log_lines):
    response = client.get("/api/health")
    generated = response.headers["X-Request-ID"]
    assert len(generated) >= 16
    assert log_lines()[-1]["request_id"] == generated


def test_unsafe_client_request_id_is_replaced(client):
    response = client.get("/api/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["X-Request-ID"] != "bad id\twith spaces"


def test_unknown_route_logs_path_and_404(client, log_lines):
    client.get("/api/nope")
    entry = log_lines()[-1]
    assert entry["status"] == 404
    assert entry["route"] == "/api/nope"
