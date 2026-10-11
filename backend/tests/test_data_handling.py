"""Insecure data handling: how uploads are stored and read, how big a request may be, that the
front end never renders anything as HTML, and that the database is not open to the network."""

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.security.http import MAX_JSON_BYTES, MAX_UPLOAD_REQUEST_BYTES
from tests.conftest import BACKEND_DIR, login
from tests.fakes import extraction

ROOT = BACKEND_DIR.parent
pytestmark = pytest.mark.usefixtures("people")


# --- request size (a very large body should be refused before it is read) -------------------


def test_an_oversized_upload_is_refused_up_front_from_its_declared_size(client, people):
    login(client, people.coordinator)
    response = client.post(
        "/api/donations",
        content=b"x",
        headers={
            "content-length": str(MAX_UPLOAD_REQUEST_BYTES + 1),
            "content-type": "multipart/form-data; boundary=x",
        },
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.json()["error"]["request_id"]


def test_a_large_json_body_is_refused(client, people):
    login(client, people.coordinator)
    response = client.post(
        "/api/allocations/bulk-approve",
        content=b"{}",
        headers={"content-length": str(MAX_JSON_BYTES + 1), "content-type": "application/json"},
    )
    assert response.status_code == 413


def test_a_normal_upload_and_a_normal_body_are_not_affected(client, people):
    login(client, people.coordinator)
    client.app.state.llm.script(extraction())
    assert (
        client.post(
            "/api/donations", files={"file": ("m.txt", b"10 cases", "text/plain")}
        ).status_code
        == 201
    )
    assert client.post("/api/allocations/bulk-approve", json={"ids": [1]}).status_code != 413


def test_the_upload_limit_leaves_room_for_a_10_mb_file():
    assert MAX_UPLOAD_REQUEST_BYTES > 10 * 1024 * 1024


# --- where files live and who can read them ---------------------------------------------------


def test_uploaded_files_are_kept_outside_every_folder_that_is_served():
    storage = Settings().storage_path.resolve()
    for public in (
        ROOT / "frontend" / "public",
        ROOT / "frontend" / "src",
        ROOT / "frontend" / ".next",
    ):
        assert public.resolve() not in storage.parents and storage != public.resolve()


def test_no_route_hands_back_a_stored_file(client):
    paths = " ".join(client.app.openapi()["paths"] if client.app.openapi_url else [])
    assert "download" not in paths and "/files" not in paths
    from app.main import create_app  # the real app, with docs on, only to read its route list

    spec = create_app(Settings(expose_api_docs=True), client.app.state.engine).openapi()
    for path in spec["paths"]:
        assert not re.search(r"file|download|upload/|static|storage", path, re.IGNORECASE), path


def test_stored_files_get_random_names_never_the_uploaded_name(client, people):
    login(client, people.coordinator)
    client.app.state.llm.script(extraction())
    response = client.post(
        "/api/donations", files={"file": ("../../etc/passwd.txt", b"10 cases", "text/plain")}
    )
    assert response.status_code == 201
    stored = [p for p in Path(client.app.state.storage.root).rglob("*") if p.is_file()]
    assert stored and all(re.fullmatch(r"[0-9a-f]{32}\.txt", p.name) for p in stored)
    assert all("passwd" not in str(p) for p in stored)


# --- the front end never renders text as HTML -------------------------------------------------


FRONTEND_SRC = ROOT / "frontend" / "src"
DANGEROUS = re.compile(
    r"dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|document\.write|insertAdjacentHTML|\beval\(|new Function\("
)


def test_the_front_end_never_uses_an_html_injection_api():
    offenders = [
        str(p.relative_to(ROOT))
        for p in FRONTEND_SRC.rglob("*.ts*")
        if DANGEROUS.search(p.read_text())
    ]
    assert offenders == []


# --- the database is not open to the network --------------------------------------------------


def test_postgres_is_published_on_the_loopback_address_only():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    ports = compose["services"]["postgres"]["ports"]
    assert ports and all(str(p).startswith("127.0.0.1:") for p in ports)


def test_the_compose_file_has_no_password_in_it():
    text_ = (ROOT / "docker-compose.yml").read_text()
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD" in text_  # read from .env, never written here


# --- secrets in the repository ----------------------------------------------------------------


def test_env_is_ignored_and_the_example_has_no_real_secret():
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignore and "!.env.example" in ignore
    example = (ROOT / ".env.example").read_text()
    for line in example.splitlines():
        if line.startswith(("JWT_SECRET=", "POSTGRES_PASSWORD=")):
            assert line.split("=", 1)[1] == "", line  # the blanks must be filled in locally
    assert "AKIA" not in example and "aws_secret" not in example.lower()
