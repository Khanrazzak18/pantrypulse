"""AI monthly summary: aggregates only, every number checked, admin edits and approves."""

import json

import pytest
from sqlalchemy import text

from app.ai.llm_provider import LLMTimeout
from app.services import summaries
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people", "impact_world")
MONTH = "2026-09"


@pytest.fixture
def admin(client, people):
    login(client, people.admin)
    return client


def draft(client, month=MONTH):
    return client.post(f"/api/dashboard/summaries/{month}/draft")


def say(text_):
    return {"summary": text_}


GOOD = (
    "In September 2026 the food bank's partner pantries received 710 lb of food and served 135 "
    "households. 3 shortage reports were filed, and spoilage of perishable food was 10.0%."
)


def stored(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT status, ai_draft, final_text, aggregates, model_id FROM monthly_summaries")
        ).all()


def test_aggregates_for_the_month(migrated_engine):
    from sqlalchemy.orm import Session

    with Session(migrated_engine) as db:
        a = summaries.monthly_aggregates(db, MONTH)
    assert a["pounds_distributed"] == 710 and a["households_served"] == 135
    assert a["shortage_reports"] == 3 and a["spoilage_pct"] == 10.0
    assert a["pantry_weeks_with_shortage_pct"] == 75.0
    assert {c["category"] for c in a["by_category"]} == {"produce", "canned"}
    assert a["previous_month"] is None  # nothing in August


def test_the_model_sees_the_aggregates_and_nothing_else(admin, llm):
    llm.script(say(GOOD))
    assert draft(admin).status_code == 201
    sent = json.dumps(llm.calls[0]["content"])
    assert "710" in sent and "135" in sent
    for raw in ("Impact Pantry", "Impact Donor", "Impact food", "931", "932"):
        assert raw not in sent  # no pantry, donor, item or id reaches the model
    assert llm.calls[0]["tool_name"] == "record_summary"
    assert llm.calls[0]["timeout_seconds"] is not None


def test_a_draft_with_matching_numbers_is_saved(admin, llm, engine):
    llm.script(say(GOOD))
    response = draft(admin)
    assert response.status_code == 201
    out = response.json()
    assert out["status"] == "draft" and out["ai_draft"] == GOOD and out["final_text"] is None
    ((status, ai, final, aggregates, model),) = stored(engine)
    assert status == "draft" and ai == GOOD and final is None and model == "fake-model"
    assert aggregates["pounds_distributed"] == 710


def test_a_number_that_is_not_in_the_aggregates_is_refused(admin, llm, engine):
    llm.script(say(GOOD.replace("135 households", "1,350 households")))
    response = draft(admin)
    assert response.status_code == 502
    err = response.json()["error"]
    assert err["code"] == "summary_numbers_mismatch" and 1350 in err["details"]["numbers"]
    assert stored(engine) == []  # nothing is saved


def test_a_model_failure_is_a_readable_error(admin, llm, engine):
    llm.script(LLMTimeout("slow"))
    response = draft(admin)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "summary_failed"
    assert len(llm.calls) == 1  # no retry inside the request; the admin retries
    assert stored(engine) == []


def test_a_reply_without_the_tool_call_is_an_error(admin, llm):
    llm.script("I would rather chat")
    assert draft(admin).json()["error"]["code"] == "summary_failed"


def test_retry_after_a_failure_works(admin, llm):
    llm.script(LLMTimeout("slow"))
    assert draft(admin).status_code == 502
    llm.script(say(GOOD))
    assert draft(admin).status_code == 201


def test_a_month_with_no_data_has_nothing_to_summarise(admin, llm):
    response = draft(admin, "2020-01")
    assert response.status_code == 422 and response.json()["error"]["code"] == "no_data"
    assert llm.calls == []


@pytest.mark.parametrize("month", ["2026-13", "September", "2026-09-01", "26-09"])
def test_the_month_must_be_yyyy_mm(admin, month):
    assert draft(admin, month).status_code in (404, 422)


def test_approving_saves_the_edited_text_as_final(admin, llm, engine, people):
    llm.script(say(GOOD))
    draft(admin)
    edited = GOOD + " Thank you to our donors."
    response = admin.post(f"/api/dashboard/summaries/{MONTH}/approve", json={"text": edited})
    assert response.status_code == 200
    assert response.json()["status"] == "approved" and response.json()["final_text"] == edited
    ((status, ai, final, _, _),) = stored(engine)
    assert (status, ai, final) == ("approved", GOOD, edited)  # the AI draft is kept for the record
    with engine.connect() as conn:
        who = conn.execute(
            text("SELECT u.email FROM monthly_summaries m JOIN users u ON u.id = m.approved_by")
        ).scalar()
    assert who == people.admin


def test_the_admin_can_write_it_themselves(admin, engine):
    response = admin.post(
        f"/api/dashboard/summaries/{MONTH}/approve", json={"text": "My own words."}
    )
    assert response.status_code == 200
    ((status, ai, final, aggregates, model),) = stored(engine)
    assert (status, ai, final, model) == ("approved", "", "My own words.", None)
    assert aggregates["pounds_distributed"] == 710


def test_an_approved_summary_is_final(admin, llm):
    admin.post(f"/api/dashboard/summaries/{MONTH}/approve", json={"text": "Done."})
    again = admin.post(f"/api/dashboard/summaries/{MONTH}/approve", json={"text": "Changed."})
    assert again.status_code == 409 and again.json()["error"]["code"] == "summary_approved"
    llm.script(say(GOOD))
    assert draft(admin).status_code == 409
    assert llm.calls == []


def test_a_new_draft_replaces_an_unapproved_one(admin, llm, engine):
    llm.script(say(GOOD), say(GOOD.replace("10.0%", "10%")))
    draft(admin)
    draft(admin)
    assert len(stored(engine)) == 1


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}, {"text": "x" * 4001}, {}])
def test_approval_needs_text(admin, body):
    assert admin.post(f"/api/dashboard/summaries/{MONTH}/approve", json=body).status_code == 422


def test_reading_a_month(admin, llm):
    assert admin.get(f"/api/dashboard/summaries/{MONTH}").json() == {"summary": None}
    llm.script(say(GOOD))
    draft(admin)
    assert admin.get(f"/api/dashboard/summaries/{MONTH}").json()["summary"]["status"] == "draft"


def test_only_admins_draft_or_approve(client, people, llm):
    llm.script(say(GOOD))
    assert draft(client).status_code == 401
    for email in (people.coordinator, people.manager):
        client.cookies.clear()
        login(client, email)
        assert draft(client).status_code == 403
        assert (
            client.post(f"/api/dashboard/summaries/{MONTH}/approve", json={"text": "x"}).status_code
            == 403
        )
        assert client.get(f"/api/dashboard/summaries/{MONTH}").status_code == 403
    assert llm.calls == []
