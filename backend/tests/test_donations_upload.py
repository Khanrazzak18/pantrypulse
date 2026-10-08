"""POST /api/donations: validate, read with the (scripted) model, store, create a pending donation."""

import io
import json
import random

import pytest
from PIL import Image
from sqlalchemy import text

from app.ai.llm_provider import (
    LLMAccessDenied,
    LLMNotConfigured,
    LLMThrottled,
    LLMTimeout,
    LLMUnavailable,
)
from app.constants import CATEGORY_NAMES
from tests.conftest import login, row_count
from tests.fakes import extraction, item

pytestmark = pytest.mark.usefixtures("clean_donations", "people")

EML = (
    b"From: Greenfield Market <d@greenfield.example.com>\r\nSubject: Chicken Friday\r\n"
    b"Date: Fri, 02 Oct 2026 09:30:00 -0400\r\n\r\n10 cases chicken thighs, best by 10/12\r\n"
)
PDF = b"%PDF-1.7\n" + b"x" * 200


def png(size=(60, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def upload(client, name="mail.eml", data=EML, ctype="application/octet-stream"):
    return client.post("/api/donations", files={"file": (name, data, ctype)})


@pytest.fixture
def coordinator(client, people):
    login(client, people.coordinator)
    return client


def stored_files(storage) -> list:
    root = storage.root
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def counts(engine) -> dict:
    return {t: row_count(engine, t) for t in ("donations", "donation_items", "inventory_lots")}


# --- success ----------------------------------------------------------------------------------


def test_upload_creates_a_pending_donation_with_the_extracted_items(
    coordinator, llm, storage, migrated_engine
):
    llm.script(extraction([item(name="Chicken thighs"), item(name="Eggs", category="dairy")]))
    response = upload(coordinator)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending_review" and body["source_type"] == "email"
    assert body["original_filename"] == "mail.eml"
    assert body["suggested_donor_name"] == "Greenfield Market" and body["donor_id"] is None
    assert [i["name"] for i in body["items"]] == ["Chicken thighs", "Eggs"]
    assert body["items"][0]["confidence"]["name"] == 0.95
    assert body["item_count"] == 2 and body["total_lbs"] == 800
    assert body["model_id"] == "fake-model" and body["latency_ms"] == 1850
    assert (body["input_tokens"], body["output_tokens"]) == (1200, 340)
    assert len(stored_files(storage)) == 1


def test_the_raw_model_output_is_stored_as_jsonb_with_usage(coordinator, llm, migrated_engine):
    llm.script(extraction([item(name="Chicken thighs")]))
    upload(coordinator)
    with migrated_engine.connect() as conn:
        raw, file_key, model_id = conn.execute(
            text("SELECT raw_llm_output, file_key, model_id FROM donations")
        ).one()
    assert raw["tool_input"]["items"][0]["name"] == "Chicken thighs"
    assert raw["parsed"]["items"][0]["category"] == "protein"
    assert raw["usage"] == {"input_tokens": 1200, "output_tokens": 340}
    assert raw["attempts"] == 1
    assert file_key.startswith("donations/") and file_key.endswith(".eml")
    assert model_id == "fake-model"


def test_nothing_enters_inventory_until_the_coordinator_confirms(coordinator, llm, migrated_engine):
    """Rule 9: model output never writes items or lots on its own."""
    llm.script(extraction())
    assert upload(coordinator).status_code == 201
    assert counts(migrated_engine) == {"donations": 1, "donation_items": 0, "inventory_lots": 0}


def test_the_stored_file_is_exactly_what_was_uploaded(coordinator, llm, storage):
    llm.script(extraction())
    upload(coordinator, "mail.eml", EML)
    assert stored_files(storage)[0].read_bytes() == EML


def test_the_model_is_asked_through_a_forced_tool_with_the_pydantic_schema(coordinator, llm):
    llm.script(extraction())
    upload(coordinator)
    call = llm.calls[0]
    assert call["tool_name"] == "record_donation_items"
    item_props = call["schema"]["properties"]["items"]["items"]["properties"]
    assert item_props["category"]["enum"] == list(CATEGORY_NAMES)
    assert "frozen chicken" in call["system"].lower()
    assert "Chicken Friday" in call["content"][0]["text"]


@pytest.mark.parametrize(
    ("name", "data", "source", "block_key"),
    [
        ("m.pdf", PDF, "pdf", "document"),
        ("p.png", None, "image", "image"),
        ("n.txt", b"5 cases of beans", "text", "text"),
        ("m.eml", EML, "email", "text"),
    ],
)
def test_each_file_kind_reaches_the_model_in_the_right_block(
    coordinator, llm, name, data, source, block_key
):
    llm.script(extraction())
    response = upload(coordinator, name, png() if data is None else data)
    assert response.status_code == 201
    assert response.json()["source_type"] == source
    assert block_key in llm.calls[0]["content"][0]


def test_uploaded_filenames_never_become_storage_paths(coordinator, llm, storage):
    llm.script(extraction())
    response = upload(coordinator, "../../etc/passwd.txt", b"3 cases of rice")
    assert response.json()["original_filename"] == "passwd.txt"
    (path,) = stored_files(storage)
    assert "passwd" not in path.name and path.is_relative_to(storage.root)


def test_images_over_the_model_limit_are_shrunk_but_the_original_is_kept(coordinator, llm, storage):
    noise = Image.frombytes("RGB", (1400, 1400), random.Random(2).randbytes(1400 * 1400 * 3))
    out = io.BytesIO()
    noise.save(out, "PNG")
    original = out.getvalue()
    assert 3.75 * 1024 * 1024 < len(original) < 10 * 1024 * 1024
    llm.script(extraction())
    assert upload(coordinator, "scan.png", original).status_code == 201
    sent = llm.calls[0]["content"][0]["image"]
    assert sent["format"] == "jpeg" and len(sent["source"]["bytes"]) <= 3.75 * 1024 * 1024
    assert stored_files(storage)[0].read_bytes() == original


# --- retries ---------------------------------------------------------------------------------------


def test_invalid_output_then_a_good_answer_succeeds_on_the_retry(coordinator, llm, sleeps):
    llm.script({"items": "not a list"}, extraction())
    response = upload(coordinator)
    assert response.status_code == 201
    assert len(llm.calls) == 2 and len(sleeps) == 1
    retry_text = " ".join(b["text"] for b in llm.calls[1]["content"] if "text" in b)
    assert "rejected" in retry_text and "items" in retry_text
    assert "rejected" not in " ".join(b["text"] for b in llm.calls[0]["content"] if "text" in b)


def test_an_answer_that_breaks_the_schema_counts_as_invalid(coordinator, llm):
    llm.script(extraction([item(quantity=-5)]), extraction())
    assert upload(coordinator).status_code == 201
    assert len(llm.calls) == 2


def test_invalid_output_twice_fails_clearly_and_saves_nothing(
    coordinator, llm, storage, migrated_engine
):
    llm.script({"items": []} | {"donor_name": 5}, "I could not read it")
    response = upload(coordinator)
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "ai_invalid_output" and "try again" in error["message"].lower()
    assert len(llm.calls) == 2
    assert counts(migrated_engine)["donations"] == 0 and stored_files(storage) == []


def test_a_reply_without_a_tool_call_is_treated_as_invalid(coordinator, llm):
    llm.script("Sorry, I can't help.", "Still can't.")
    assert upload(coordinator).json()["error"]["code"] == "ai_invalid_output"


def test_a_timeout_then_success_works(coordinator, llm):
    llm.script(LLMTimeout("slow"), extraction())
    assert upload(coordinator).status_code == 201
    assert len(llm.calls) == 2


def test_two_timeouts_return_504_and_save_nothing(coordinator, llm, storage, migrated_engine):
    llm.script(LLMTimeout("slow"), LLMTimeout("slow again"))
    response = upload(coordinator)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ai_timeout"
    assert "took too long" in response.json()["error"]["message"]
    assert len(llm.calls) == 2  # exactly one retry
    assert counts(migrated_engine)["donations"] == 0 and stored_files(storage) == []


def test_throttling_twice_returns_a_busy_message(coordinator, llm):
    llm.script(LLMThrottled("a"), LLMThrottled("b"))
    response = upload(coordinator)
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_busy"


def test_access_problems_are_not_retried_and_do_not_leak_details(coordinator, llm, migrated_engine):
    llm.script(LLMAccessDenied("arn:aws:iam::123456789012:user/secret is not authorized"))
    response = upload(coordinator)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ai_unavailable"
    assert "administrator" in response.json()["error"]["message"].lower()
    assert "arn:aws" not in response.text and "123456789012" not in response.text
    assert len(llm.calls) == 1 and counts(migrated_engine)["donations"] == 0


def test_a_server_side_ai_error_is_retried_once(coordinator, llm):
    llm.script(LLMUnavailable("503", retryable=True), extraction())
    assert upload(coordinator).status_code == 201


def test_a_missing_model_id_says_ai_intake_is_not_set_up(coordinator, llm):
    llm.script(LLMNotConfigured("BEDROCK_MODEL_ID is not set in .env"))
    response = upload(coordinator)
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_not_configured"


def test_a_file_with_no_donation_items_is_reported_not_retried(coordinator, llm, migrated_engine):
    llm.script(extraction(items=[], notes="This looks like a newsletter"))
    response = upload(coordinator)
    assert response.status_code == 422 and response.json()["error"]["code"] == "no_items_found"
    assert len(llm.calls) == 1 and counts(migrated_engine)["donations"] == 0


# --- rejected files (the model is never called) -----------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["virus.exe", "notes.docx", "pic.gif", "archive.zip", "noextension", "x.pdf.exe", "p.html"],
)
def test_wrong_file_types_get_a_readable_415(coordinator, llm, name):
    response = upload(coordinator, name, b"%PDF-1.7 abc")
    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "unsupported_file_type"
    assert "PDF" in error["message"] and "EML" in error["message"]
    assert llm.calls == []


@pytest.mark.parametrize(
    ("name", "data"),
    [("fake.pdf", b"MZ\x90\x00program"), ("fake.png", b"text"), ("bin.txt", b"a\x00b")],
)
def test_files_that_are_not_what_their_extension_says_are_rejected(coordinator, llm, name, data):
    response = upload(coordinator, name, data)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_file_content"
    assert llm.calls == []


def test_a_file_over_10_mb_is_rejected_with_a_readable_413(coordinator, llm, storage):
    response = upload(coordinator, "huge.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024))
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large" and "10 MB" in error["message"]
    assert llm.calls == [] and stored_files(storage) == []


def test_exactly_10_mb_passes_the_upload_limit(coordinator, llm):
    """The generic limit is inclusive; this PDF then trips the model's own, smaller PDF limit."""
    response = upload(coordinator, "edge.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024 - 5))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large_for_ai"
    assert "4.5 MB" in response.json()["error"]["message"]


def test_an_empty_file_is_rejected(coordinator, llm):
    response = upload(coordinator, "empty.txt", b"")
    assert response.status_code == 422 and response.json()["error"]["code"] == "empty_file"


def test_a_request_without_a_file_is_a_validation_error(coordinator):
    response = coordinator.post("/api/donations", data={"note": "hi"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- failures after a good answer ---------------------------------------------------------------


def test_if_storing_the_file_fails_nothing_is_left_behind(
    coordinator, llm, storage, migrated_engine
):
    llm.script(extraction())

    def broken_put(*args, **kwargs):
        raise OSError("disk full")

    storage.put = broken_put
    response = upload(coordinator)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error" and "disk full" not in response.text
    assert counts(migrated_engine)["donations"] == 0


# --- who may upload --------------------------------------------------------------------------------


def test_logged_out_users_cannot_upload(client, llm):
    assert upload(client).status_code == 401
    assert llm.calls == []


def test_pantry_managers_cannot_upload(client, people, llm):
    login(client, people.manager)
    assert upload(client).status_code == 403
    assert llm.calls == []


def test_admins_can_upload(client, people, llm):
    login(client, people.admin)
    llm.script(extraction())
    assert upload(client).status_code == 201


def test_logs_contain_the_outcome_but_not_the_manifest(coordinator, llm):
    import logging

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    from app.logging import JsonFormatter

    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("pantrypulse")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        llm.script(extraction())
        upload(coordinator, "n.txt", b"UNIQUE-MANIFEST-CONTENT 5 cases")
    finally:
        logger.removeHandler(handler)
    logged = stream.getvalue()
    assert "UNIQUE-MANIFEST-CONTENT" not in logged
    entry = next(json.loads(x) for x in logged.splitlines() if '"donation_extracted"' in x)
    assert entry["items"] == 1 and entry["attempts"] == 1 and entry["input_tokens"] == 1200
