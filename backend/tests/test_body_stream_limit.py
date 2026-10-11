"""The request size limit is enforced while the body streams in, so a request with no
Content-Length (chunked), or one that lies about its length, is bounded too."""

import asyncio

import pytest

from app.security.http import MAX_JSON_BYTES, MAX_UPLOAD_REQUEST_BYTES
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people")
CHUNK = b"x" * 65536


def chunks(total: int):
    sent = 0
    while sent < total:
        piece = CHUNK[: min(len(CHUNK), total - sent)]
        sent += len(piece)
        yield piece


def test_a_chunked_json_body_over_the_limit_is_refused_without_a_content_length(client, people):
    login(client, people.coordinator)
    response = client.post(
        "/api/allocations/bulk-approve",
        content=chunks(MAX_JSON_BYTES + 1),  # a generator: sent chunked, no Content-Length
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "payload_too_large" and error["request_id"]


def test_a_chunked_upload_over_the_limit_is_refused(client, people):
    login(client, people.coordinator)
    response = client.post(
        "/api/donations",
        content=chunks(MAX_UPLOAD_REQUEST_BYTES + 1),
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_a_chunked_body_just_under_the_limit_is_not_refused_for_its_size(client, people):
    login(client, people.coordinator)
    response = client.post(
        "/api/allocations/bulk-approve",
        content=chunks(1000),
        headers={"content-type": "application/json"},
    )
    assert response.status_code != 413  # (it is not valid JSON, so some other 4xx)


def test_a_request_that_lies_about_a_small_length_is_stopped_when_it_exceeds_the_limit(client):
    """Drive the app directly: Content-Length says 10 bytes, then far more arrive."""
    app = client.app
    sent = []
    received = {"bytes": 0}
    pieces = [{"type": "http.request", "body": CHUNK, "more_body": True} for _ in range(40)]
    pieces.append({"type": "http.request", "body": b"", "more_body": False})

    async def receive():
        message = pieces.pop(0) if pieces else {"type": "http.disconnect"}
        received["bytes"] += len(message.get("body", b""))
        return message

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "path": "/api/auth/login", "raw_path": b"/api/auth/login", "query_string": b"",
        "root_path": "", "scheme": "http", "server": ("testserver", 80), "client": ("1.2.3.4", 1),
        "headers": [(b"content-type", b"application/json"), (b"content-length", b"10"),
                    (b"host", b"testserver")],
    }  # fmt: skip
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413
    assert received["bytes"] <= MAX_JSON_BYTES + len(CHUNK)  # it stopped reading at the limit


def test_the_limit_is_per_request_so_the_next_request_is_fine(client, people):
    login(client, people.coordinator)
    client.post("/api/allocations/bulk-approve", content=chunks(MAX_JSON_BYTES + 1),
                headers={"content-type": "application/json"})  # fmt: skip
    assert client.get("/api/health").status_code == 200
