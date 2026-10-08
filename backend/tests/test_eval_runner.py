import json

import pytest

from eval import run_intake_eval as runner
from eval.scoring import aggregate


def exp(**kw):
    base = {"name": "Chicken thighs", "category": "protein", "quantity": 10, "unit": "case",
            "estimated_weight_lbs": 400.0, "expiry_date": "2026-10-14", "storage_type": "refrigerated"}  # fmt: skip
    return {**base, **kw}


CASES = [
    {
        "id": "001",
        "format": "email",
        "donor_name": "Acme Foods",
        "items": [exp(), exp(name="Eggs")],
    },
    {
        "id": "002",
        "format": "pdf",
        "donor_name": "Bright Farm",
        "items": [exp(name="Carrots", category="produce")],
    },
    {
        "id": "003",
        "format": "image",
        "donor_name": None,
        "items": [exp(name="Rice", category="dry_goods")],
    },
]


def oracle(case):
    return runner.Extracted(
        actual={"donor_name": case["donor_name"], "items": case["items"]},
        input_tokens=1000, output_tokens=200, latency_ms=1500, attempts=1,
    )  # fmt: skip


def test_an_oracle_scores_100_percent_and_usage_is_summed():
    run = runner.run_cases(CASES, oracle, concurrency=1)
    summary = aggregate([r.score for r in run.results])
    assert summary.accuracy == 1.0
    assert (run.input_tokens, run.output_tokens) == (3000, 600)
    assert run.total_latency_ms == 4500


def test_failures_are_recorded_and_score_zero_but_do_not_stop_the_run():
    def flaky(case):
        if case["id"] == "002":
            raise runner.CaseFailed("ApiError ai_timeout")
        return oracle(case)

    run = runner.run_cases(CASES, flaky, concurrency=1)
    failed = [r for r in run.results if r.error]
    assert [r.case["id"] for r in failed] == ["002"] and failed[0].error == "ApiError ai_timeout"
    assert aggregate([r.score for r in run.results]).failed_cases == 1


def test_concurrent_runs_keep_results_in_case_order():
    run = runner.run_cases(CASES, oracle, concurrency=3)
    assert [r.case["id"] for r in run.results] == ["001", "002", "003"]


def test_the_report_has_the_headline_numbers_and_the_target_verdict(tmp_path):
    run = runner.run_cases(CASES, oracle, concurrency=1)
    text = runner.render_report(run, model_id="test-model", target=0.95, when="2026-10-08 12:00")
    for needle in (
        "test-model",
        "100.0%",
        "PASS",
        "Input tokens",
        "3,000",
        "Output tokens",
        "600",
        "email",
        "pdf",
        "image",
        "estimated_weight_lbs",
    ):
        assert needle in text, needle
    path = tmp_path / "intake-eval.md"
    runner.write_report(path, text)
    assert path.read_text() == text


def test_below_target_says_so_and_lists_the_mistakes():
    def sloppy(case):
        out = oracle(case)
        items = [dict(i, category="dairy") for i in out.actual["items"]]
        return runner.Extracted({**out.actual, "items": items}, 1000, 200, 1500, 1)

    run = runner.run_cases(CASES, sloppy, concurrency=1)
    text = runner.render_report(run, model_id="m", target=0.95, when="now")
    assert "BELOW TARGET" in text and "category" in text and "001" in text


def test_the_eval_refuses_to_run_without_a_model_id(monkeypatch, settings):
    monkeypatch.setattr(
        runner, "get_settings", lambda: settings.model_copy(update={"bedrock_model_id": ""})
    )
    with pytest.raises(SystemExit, match="BEDROCK_MODEL_ID"):
        runner.main([])


def test_results_can_be_saved_as_json(tmp_path):
    run = runner.run_cases(CASES, oracle, concurrency=1)
    path = tmp_path / "latest.json"
    runner.write_results_json(path, run, model_id="m")
    saved = json.loads(path.read_text())
    assert saved["model_id"] == "m" and len(saved["cases"]) == 3
    assert saved["cases"][0]["correct"] == 14 and saved["usage"]["input_tokens"] == 3000


# --- rescoring saved answers (no model calls) ----------------------------------------------------


def test_saved_results_include_per_case_usage_and_run_totals(tmp_path):
    run = runner.run_cases(CASES, oracle, concurrency=1)
    path = tmp_path / "latest.json"
    runner.write_results_json(path, run, model_id="m", when="2026-10-08 12:00")
    saved = json.loads(path.read_text())
    assert saved["run_at"] == "2026-10-08 12:00"
    assert saved["cases"][0]["input_tokens"] == 1000 and saved["cases"][0]["attempts"] == 1
    assert saved["usage"]["retried_cases"] == 0 and saved["usage"]["wall_seconds"] >= 0


def test_rescoring_reproduces_the_run_and_keeps_its_usage(tmp_path):
    run = runner.run_cases(CASES, oracle, concurrency=1)
    path = tmp_path / "latest.json"
    runner.write_results_json(path, run, model_id="m", when="2026-10-08 12:00")
    again, meta = runner.load_results(path, CASES)
    assert meta == {"model_id": "m", "run_at": "2026-10-08 12:00"}
    assert aggregate([r.score for r in again.results]).accuracy == 1.0
    assert (again.input_tokens, again.output_tokens) == (3000, 600)


def test_rescoring_uses_the_golden_answers_it_is_given_not_the_ones_from_the_run(tmp_path):
    run = runner.run_cases(CASES, oracle, concurrency=1)
    path = tmp_path / "latest.json"
    runner.write_results_json(path, run, model_id="m", when="then")
    stricter = [dict(c, items=[dict(i, category="dairy") for i in c["items"]]) for c in CASES]
    again, _ = runner.load_results(path, stricter)
    assert aggregate([r.score for r in again.results]).accuracy < 1.0


def test_legacy_results_with_only_run_level_usage_still_rescore(tmp_path):
    saved = {
        "model_id": "m",
        "usage": {"input_tokens": 170445, "output_tokens": 53773, "total_latency_ms": 265000},
        "cases": [{"id": c["id"], "format": c["format"], "error": None,
                   "actual": {"donor_name": c["donor_name"], "items": c["items"]}} for c in CASES],
    }  # fmt: skip
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(saved))
    run, meta = runner.load_results(path, CASES)
    assert (run.input_tokens, run.output_tokens) == (170445, 53773)
    assert meta["run_at"] is None


def test_the_report_can_carry_a_scoring_note():
    run = runner.run_cases(CASES, oracle, concurrency=1)
    text = runner.render_report(run, "m", 0.95, "now", notes=["Scored again after fixing names."])
    assert "Scoring note" in text and "Scored again after fixing names." in text
