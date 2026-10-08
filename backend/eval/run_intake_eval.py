"""Run the donation-intake eval against the real model and write docs/eval/intake-eval.md.

    python -m eval.run_intake_eval            # all 50 golden manifests (this calls Bedrock)
    python -m eval.run_intake_eval --limit 5  # a quick smoke run

It uses exactly the code path the app uses (upload checks, prompt, forced tool call, validation,
one retry), then scores the answers field by field (see eval/scoring.py).
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.ai.llm_provider import BedrockProvider
from app.config import ROOT, get_settings
from app.errors import ApiError
from app.services import intake
from eval import golden_key
from eval.make_golden_set import GOLDEN_DIR
from eval.scoring import FIELDS, CaseScore, aggregate, score_case

REPORT_PATH = ROOT / "docs/eval/intake-eval.md"
RESULTS_PATH = ROOT / "backend/eval/results/latest.json"
TARGET = 0.95
MISTAKES_SHOWN = 30


class CaseFailed(Exception):
    """The model could not produce a usable answer for this manifest."""


@dataclass
class Extracted:
    actual: dict
    input_tokens: int
    output_tokens: int
    latency_ms: int
    attempts: int


@dataclass
class CaseResult:
    case: dict
    score: CaseScore
    extracted: Extracted | None
    error: str | None = None


@dataclass
class Run:
    results: list[CaseResult] = field(default_factory=list)
    seconds: float = 0.0
    # Run-level usage restored from an older results file that did not record it per case.
    fixed_usage: dict | None = None

    def _total(self, key: str, per_case) -> int:
        if self.fixed_usage and key in self.fixed_usage:
            return int(self.fixed_usage[key])
        return sum(per_case(r.extracted) for r in self.results if r.extracted)

    @property
    def input_tokens(self) -> int:
        return self._total("input_tokens", lambda e: e.input_tokens)

    @property
    def output_tokens(self) -> int:
        return self._total("output_tokens", lambda e: e.output_tokens)

    @property
    def total_latency_ms(self) -> int:
        return self._total("total_latency_ms", lambda e: e.latency_ms)

    @property
    def retried_cases(self) -> int:
        return self._total("retried_cases", lambda e: int(e.attempts > 1))


def load_cases(root: Path = GOLDEN_DIR) -> list[dict]:
    cases = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        spec = json.loads((case_dir / "expected.json").read_text())
        spec["path"] = str(case_dir / spec["file"])
        cases.append(spec)
    return cases


def make_extractor(llm):
    """The extract function the real eval uses: same code path as the upload endpoint."""

    def extract(case: dict) -> Extracted:
        path = Path(case["path"])
        today = date.fromisoformat(case["received_date"])
        try:
            prepared = intake.prepare_upload(path.name, path.read_bytes())
            outcome = intake.extract_items(llm, prepared, today)
        except ApiError as exc:
            raise CaseFailed(f"{exc.code}: {exc.message}") from exc
        return Extracted(
            actual=outcome.extraction.model_dump(mode="json"),
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_ms=outcome.result.latency_ms,
            attempts=outcome.attempts,
        )

    return extract


def run_cases(cases: list[dict], extract, concurrency: int = 4) -> Run:
    def one(case: dict) -> CaseResult:
        try:
            extracted = extract(case)
        except CaseFailed as exc:
            return CaseResult(case, score_case(case, None), None, str(exc))
        return CaseResult(case, score_case(case, extracted.actual), extracted)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, cases))  # map keeps the golden-set order
    return Run(results, time.perf_counter() - started)


# --- reporting -------------------------------------------------------------------------------


def _pct(correct: int, total: int) -> str:
    return f"{100 * correct / total:.1f}%" if total else "n/a"


def _mistakes(run: Run) -> list[str]:
    lines = []
    for result in run.results:
        if result.error:
            lines.append(
                f"- **{result.case['id']}** ({result.case['format']}): FAILED, {result.error}"
            )
            continue
        for item in result.score.items:
            if item.got is None:
                lines.append(
                    f"- **{result.case['id']}** ({result.case['format']}): missed item "
                    f"'{item.expected['name']}'"
                )
                continue
            wrong = [
                f"{f}: expected `{item.expected.get(f)}`, got `{item.got.get(f)}`"
                for f in FIELDS
                if not item.fields[f]
            ]
            if wrong:
                lines.append(
                    f"- **{result.case['id']}** ({result.case['format']}) '{item.expected['name']}': "
                    + "; ".join(wrong)
                )
        if result.score.extra:
            lines.append(
                f"- **{result.case['id']}** ({result.case['format']}): {result.score.extra} extra item(s)"
            )
    return lines


def render_report(
    run: Run, model_id: str, target: float, when: str, notes: list[str] | None = None
) -> str:
    summary = aggregate([r.score for r in run.results])
    verdict = "PASS" if summary.accuracy >= target else "BELOW TARGET"
    formats = ", ".join(
        f"{sum(1 for r in run.results if r.case['format'] == f)} {f}" for f in summary.by_format
    )
    n = max(1, len(run.results))
    lines = [
        "# Donation intake eval",
        "",
        f"- Run: {when}",
        f"- Model: `{model_id}` (Amazon Bedrock Converse, forced tool call, temperature 0)",
        f"- Golden set: {summary.cases} synthetic manifests ({formats})",
        f"- Target: field-level accuracy of at least {target:.0%}",
        "",
        "## Result",
        "",
        f"**Field-level accuracy: {_pct(summary.correct, summary.total)}** "
        f"({summary.correct:,} of {summary.total:,} expected fields correct): **{verdict}**",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Items found | {summary.items_expected - summary.items_missed} of {summary.items_expected} ({summary.item_recall:.1%}) |",
        f"| Extra items invented | {summary.extra_items} |",
        f"| Donor name correct | {summary.donors_correct} of {summary.cases} |",
        f"| Manifests that failed outright | {summary.failed_cases} |",
        f"| Manifests that needed the retry | {run.retried_cases} |",
        "",
        "## Accuracy by field",
        "",
        "| Field | Correct | Accuracy |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {f} | {c} of {t} | {_pct(c, t)} |" for f, (c, t) in summary.by_field.items()]
    lines += [
        "",
        "## Accuracy by format",
        "",
        "| Format | Correct | Accuracy |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {f} | {c} of {t} | {_pct(c, t)} |" for f, (c, t) in summary.by_format.items()]
    lines += [
        "",
        "## Token usage and time",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Input tokens | {run.input_tokens:,} |",
        f"| Output tokens | {run.output_tokens:,} |",
        f"| Total tokens | {run.input_tokens + run.output_tokens:,} |",
        f"| Average per manifest | {run.input_tokens // n:,} in / {run.output_tokens // n:,} out |",
        f"| Average model latency | {run.total_latency_ms / n / 1000:.1f} s |",
        f"| Wall-clock time for the run | {run.seconds:.0f} s |",
        "",
        "Token counts include answers that were rejected and retried.",
        "",
        *(["## Scoring note", "", *notes, ""] if notes else []),
        "## Results history",
        "",
        "| Run | Prompt | Answer key | Accuracy |",
        "| --- | --- | --- | --- |",
        "| 1 (Stage 4) | first | first key | 92.9% (1,867 of 2,009) |",
        "| 1, rescored | first | corrected after seeing run 1 | 98.7% (1,982 of 2,009) |",
        "| 2 (Stage 8) | with the Stage 8 fixes | frozen (`eval/golden/KEY.sha256`) | "
        "see Result above |",
        "",
        "How much to trust run 2: the key was frozen and committed before the prompt changed, and "
        "`make eval` refuses to run if it differs, so nobody could help the score by editing "
        "answers. It is still not a blind test. The prompt fixes (default storage by food, milk, "
        "weights per unit, month-only and year-less dates) were written to cure mistakes seen on "
        "this same set in run 1, using different example foods, and the set is synthetic and was "
        "written with the same rules as the prompt. Read it as 'the known mistakes are fixed', "
        "not as accuracy on real manifests. It is one run at temperature 0; a different run could "
        "differ by a field or two.",
        "",
        "## How a field is scored",
        "",
        "Each expected item has 7 fields. A field is correct if the model's matching item agrees:",
        "name (same food, ignoring case, plurals and filler words), category, unit (after",
        "normalising plurals and abbreviations), storage type and expiry date (exact; a missing",
        "date is correct only if none was expected), quantity (within 1%) and estimated weight",
        "(within 5%). An expected item the model missed counts as 7 wrong fields. Extra items are",
        "reported but do not change the accuracy. Weights the manifest does not state are expected",
        "to follow the typical case weights written in the prompt.",
        "",
        "## Mistakes",
        "",
    ]
    mistakes = _mistakes(run)
    if mistakes:
        lines += mistakes[:MISTAKES_SHOWN]
        if len(mistakes) > MISTAKES_SHOWN:
            lines.append(f"- ... and {len(mistakes) - MISTAKES_SHOWN} more")
    else:
        lines.append("None: every field of every item was correct.")
    return "\n".join(lines) + "\n"


def write_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_results_json(path: Path, run: Run, model_id: str, when: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_id": model_id,
        "run_at": when,
        "usage": {
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "total_latency_ms": run.total_latency_ms,
            "retried_cases": run.retried_cases,
            "wall_seconds": round(run.seconds, 1),
        },
        "cases": [
            {
                "id": r.case["id"],
                "format": r.case["format"],
                "correct": r.score.correct,
                "total": r.score.total,
                "missed": r.score.missed,
                "extra": r.score.extra,
                "error": r.error,
                "input_tokens": r.extracted.input_tokens if r.extracted else 0,
                "output_tokens": r.extracted.output_tokens if r.extracted else 0,
                "latency_ms": r.extracted.latency_ms if r.extracted else 0,
                "attempts": r.extracted.attempts if r.extracted else 0,
                "actual": r.extracted.actual if r.extracted else None,
            }
            for r in run.results
        ],
    }
    path.write_text(json.dumps(payload, indent=2))


def load_results(path: Path, cases: list[dict]) -> tuple[Run, dict]:
    """Rebuild a run from saved model answers and score it against the golden answers in `cases`.

    No model is called: this is how a scoring fix is applied to answers that already exist.
    """
    saved = json.loads(path.read_text())
    by_id = {c["id"]: c for c in cases}
    results = []
    for entry in saved["cases"]:
        case = by_id[entry["id"]]
        actual = entry.get("actual")
        extracted = (
            Extracted(
                actual,
                entry.get("input_tokens", 0),
                entry.get("output_tokens", 0),
                entry.get("latency_ms", 0),
                entry.get("attempts", 1),
            )
            if actual is not None
            else None
        )
        results.append(CaseResult(case, score_case(case, actual), extracted, entry.get("error")))
    usage = saved.get("usage", {})
    run = Run(results, float(usage.get("wall_seconds", 0)), fixed_usage=usage)
    return run, {"model_id": saved["model_id"], "run_at": saved.get("run_at")}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="only the first N manifests")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--target", type=float, default=TARGET)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument(
        "--rescore", action="store_true", help="score the saved answers again (no model calls)"
    )
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument(
        "--note", action="append", default=[], help="a line for the report's scoring note"
    )
    args = parser.parse_args(argv)
    golden_key.assert_frozen()

    if args.rescore:
        run, meta = load_results(args.results, load_cases())
        when = meta["run_at"] or "unknown"
        text = render_report(run, meta["model_id"], args.target, when, args.note or None)
        write_report(args.report, text)
        summary = aggregate([r.score for r in run.results])
        print(
            f"Rescored {len(run.results)} saved answers (no model calls): "
            f"{summary.accuracy:.1%} ({summary.correct}/{summary.total}). Report: {args.report}"
        )
        return

    settings = get_settings()
    if not settings.bedrock_model_id:
        raise SystemExit("make eval calls Bedrock: set BEDROCK_MODEL_ID in .env first.")
    cases = load_cases()[: args.limit]
    print(f"Running {len(cases)} manifests against {settings.bedrock_model_id} ...")
    run = run_cases(cases, make_extractor(BedrockProvider(settings)), args.concurrency)

    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = render_report(run, settings.bedrock_model_id, args.target, when)
    if args.limit is None:  # a partial run must not overwrite the full report
        write_report(args.report, text)
        print(f"Report written to {args.report}")
    write_results_json(RESULTS_PATH, run, settings.bedrock_model_id, when)
    summary = aggregate([r.score for r in run.results])
    print(
        f"Field accuracy {summary.accuracy:.1%} "
        f"({summary.correct}/{summary.total}); failed {summary.failed_cases}; "
        f"tokens in {run.input_tokens:,} / out {run.output_tokens:,}"
    )


if __name__ == "__main__":
    main()
