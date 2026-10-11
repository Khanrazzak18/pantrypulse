"""The end-to-end helpers (mock AI, reset route) must be impossible to switch on in the real app."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.main import create_app
from tests.conftest import BACKEND_DIR

APP_DIR = BACKEND_DIR / "app"
E2E_WORDS = re.compile(r"e2e_server|e2e_llm|e2e_setup|MockLLM|__e2e|E2E_MODE", re.IGNORECASE)


def test_nothing_under_app_mentions_the_e2e_helpers():
    offenders = [
        str(p.relative_to(BACKEND_DIR))
        for p in APP_DIR.rglob("*.py")
        if E2E_WORDS.search(p.read_text())
    ]
    assert offenders == []


def test_the_normal_app_has_no_e2e_routes(settings, engine):
    app = create_app(settings, engine)
    paths = set(app.openapi()["paths"]) | {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in paths if "__e2e" in p]


def test_the_normal_app_uses_the_real_bedrock_provider(settings, engine):
    app = create_app(settings, engine)
    assert type(app.state.llm).__name__ == "BedrockProvider"


def test_the_normal_entry_points_do_not_load_the_e2e_modules():
    code = (
        "import sys; import app.main; "
        "print([m for m in sys.modules if m.startswith('scripts.e2e')])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_the_e2e_server_refuses_to_start_without_the_switch(monkeypatch):
    from scripts import e2e_server

    monkeypatch.delenv("E2E_MODE", raising=False)
    with pytest.raises(RuntimeError, match="E2E_MODE"):
        e2e_server.build_app()


def test_the_e2e_server_refuses_a_database_that_is_not_a_test_database(monkeypatch):
    from scripts import e2e_server

    monkeypatch.setenv("E2E_MODE", "1")
    monkeypatch.setenv("POSTGRES_TEST_DB", "pantrypulse")
    with pytest.raises(RuntimeError, match="_test"):
        e2e_server.build_app()


def test_the_e2e_server_uses_the_test_database_mock_ai_and_routes(monkeypatch, settings):
    from fastapi.testclient import TestClient

    from scripts import e2e_server

    monkeypatch.setenv("E2E_MODE", "1")
    app = e2e_server.build_app()
    try:
        assert type(app.state.llm).__name__ == "MockLLM"
        assert app.state.engine.url.database == settings.postgres_test_db
        with TestClient(app) as client:
            assert client.get("/__e2e/state").json()["database"] == settings.postgres_test_db
            assert client.post("/__e2e/llm", json={"mode": "nope"}).status_code >= 400
    finally:
        app.state.engine.dispose()


def test_the_makefile_dev_target_runs_the_normal_app():
    makefile = (Path(BACKEND_DIR).parent / "Makefile").read_text()
    dev = makefile.split("\ndev:")[1].split("\n\n")[0]
    assert "app.main:create_app" in dev and "e2e" not in dev.lower()


def test_the_e2e_fault_switches_work_and_a_reset_clears_them(monkeypatch):
    from fastapi.testclient import TestClient

    from scripts import e2e_server

    monkeypatch.setenv("E2E_MODE", "1")
    app = e2e_server.build_app()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.post("/__e2e/fault", json={"mode": "db_down"}).status_code == 204
            down = client.get("/api/health")
            assert down.status_code == 503 and down.json()["error"]["code"] == "service_unavailable"
            assert (
                client.post("/__e2e/reset").status_code == 204
            )  # works even while the database is "down"
            assert client.get("/api/health").status_code == 200
            assert client.post("/__e2e/fault", json={"mode": "empty_pantries"}).status_code == 204
            assert client.get("/__e2e/state").json()["fault"] == "empty_pantries"
            assert client.post("/__e2e/fault", json={"mode": "nonsense"}).status_code >= 400
            client.post("/__e2e/reset")
    finally:
        app.state.engine.dispose()


def test_the_normal_app_has_no_fault_switch(settings, engine):
    app = create_app(settings, engine)
    assert "/__e2e/fault" not in {getattr(r, "path", "") for r in app.routes}
