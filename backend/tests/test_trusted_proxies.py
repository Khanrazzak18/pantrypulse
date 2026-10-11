"""X-Forwarded-For is believed only when the direct peer is a proxy listed in TRUSTED_PROXIES."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.requests import Request

from app.main import create_app
from app.security.client_address import client_address, parse_trusted

pytestmark = pytest.mark.usefixtures("people")


def make_request(peer: str | None, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    scope = {"type": "http", "headers": headers, "client": (peer, 5000) if peer else None}
    return Request(scope)


def test_with_no_trusted_proxies_the_header_is_ignored():
    assert client_address(make_request("9.9.9.9", "1.1.1.1"), parse_trusted("")) == "9.9.9.9"


def test_a_header_from_an_unlisted_peer_is_ignored():
    trusted = parse_trusted("127.0.0.1")
    assert client_address(make_request("9.9.9.9", "1.1.1.1"), trusted) == "9.9.9.9"


def test_a_header_from_a_listed_peer_is_used():
    trusted = parse_trusted("127.0.0.1, ::1")
    assert client_address(make_request("127.0.0.1", "1.1.1.1"), trusted) == "1.1.1.1"
    assert client_address(make_request("::1", "2.2.2.2"), trusted) == "2.2.2.2"


def test_the_right_most_untrusted_entry_wins_so_a_forged_prefix_does_nothing():
    trusted = parse_trusted("127.0.0.1,10.0.0.0/8")
    # the caller sent "6.6.6.6"; our proxy appended the caller's real address; another proxy added itself
    request = make_request("127.0.0.1", "6.6.6.6, 203.0.113.7, 10.1.2.3")
    assert client_address(request, trusted) == "203.0.113.7"


def test_a_listed_peer_with_no_header_is_the_peer_itself():
    assert client_address(make_request("127.0.0.1"), parse_trusted("127.0.0.1")) == "127.0.0.1"


def test_a_missing_peer_is_unknown_and_bad_entries_are_refused():
    assert client_address(make_request(None), parse_trusted("")) == "unknown"
    with pytest.raises(ValueError):
        parse_trusted("not-an-address")


def test_garbage_in_the_header_falls_back_to_the_peer():
    trusted = parse_trusted("127.0.0.1")
    assert client_address(make_request("127.0.0.1", "garbage, ,"), trusted) == "127.0.0.1"


@pytest.fixture(autouse=True)
def clean_throttle(migrated_engine):
    wipe = "TRUNCATE login_throttle"
    with migrated_engine.begin() as conn:
        conn.execute(text(wipe))
    yield
    with migrated_engine.begin() as conn:
        conn.execute(text(wipe))


def app_for(settings, engine, trusted: str, peer: str):
    app = create_app(settings.model_copy(update={"trusted_proxies": trusted}), engine)
    return TestClient(app, raise_server_exceptions=False, client=(peer, 50000))


def test_forging_the_header_does_not_dodge_the_per_address_limit(settings, engine, people):
    with app_for(settings, engine, trusted="", peer="9.9.9.9") as client:
        for i in range(20):  # twenty different emails, each claiming a different address
            client.post("/api/auth/login", json={"email": f"p{i}@example.org", "password": "wrong-password"},
                        headers={"x-forwarded-for": f"10.0.0.{i}"})  # fmt: skip
        locked = client.post("/api/auth/login", json={"email": people.coordinator, "password": "wrong"},
                             headers={"x-forwarded-for": "10.9.9.9"})  # fmt: skip
        assert locked.status_code == 429  # all twenty counted against the one real address


def test_a_trusted_proxy_lets_each_real_caller_have_their_own_limit(settings, engine, people):
    with app_for(settings, engine, trusted="127.0.0.1", peer="127.0.0.1") as client:
        for i in range(20):  # one caller behind the proxy fails twenty times
            client.post("/api/auth/login", json={"email": f"p{i}@example.org", "password": "wrong-password"},
                        headers={"x-forwarded-for": "203.0.113.50"})  # fmt: skip
        blocked = client.post("/api/auth/login", json={"email": people.coordinator, "password": "wrong"},
                              headers={"x-forwarded-for": "203.0.113.50"})  # fmt: skip
        other = client.post("/api/auth/login", json={"email": people.coordinator, "password": "wrong"},
                            headers={"x-forwarded-for": "203.0.113.51"})  # fmt: skip
        assert blocked.status_code == 429
        assert other.status_code == 401  # a different caller behind the same proxy is not locked
