# ruff: noqa: E501
"""Write docs/testing/checklist.md and docs/testing/a11y-report.md from the last `make e2e` run.

    python -m scripts.testing_report

Inputs: scripts/testing_checklist.py (the rows), frontend/test-results/results.json (Playwright's
JSON report) and frontend/test-results/a11y/*.json (one axe scan per page, role and project).
A test belongs to a checklist row when its title contains the row's ID in square brackets, for
example "[LOGIN-04] a safe next parameter is honoured". A test marked test.fail() with a [BUG-n] in
its title is a known bug: Playwright expects it to fail, so the run stays green, and flags it the
moment the bug is fixed.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess  # nosec B404
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scripts.testing_checklist import Row, rows

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "frontend/test-results/results.json"
A11Y_DIR = ROOT / "frontend/test-results/a11y"
OUT_DIR = ROOT / "docs/testing"
ID_RE = re.compile(r"\[([A-Z0-9]+-\d+)\]")
BUG_RE = re.compile(r"\[(BUG-\d+)\]")
SEVERITIES = ("critical", "serious", "moderate", "minor")


def pytest_function_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "backend/tests").glob("test_*.py"):
        tree = ast.parse(path.read_text())
        names |= {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        }
    return names


def count_pytest() -> tuple[int, int | None]:
    """(test functions, collected test cases). The cases are more because parametrized tests run
    once per parameter."""
    functions = 0
    for path in (ROOT / "backend/tests").glob("test_*.py"):
        tree = ast.parse(path.read_text())
        functions += sum(
            isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in ast.walk(tree)
        )
    proc = subprocess.run(  # nosec B603
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT / "backend", capture_output=True, text=True,
    )  # fmt: skip
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    return functions, int(match.group(1)) if match else None


def load_e2e() -> dict[str, list[dict]]:
    """checklist ID -> every result of every test that cites it (one per project)."""
    by_id: dict[str, list[dict]] = defaultdict(list)
    if not RESULTS.exists():
        return by_id
    data = json.loads(RESULTS.read_text())

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                title = spec["title"]
                bug = BUG_RE.search(title)
                outcome = test.get("status")  # expected | unexpected | flaky | skipped
                if outcome == "expected" and test.get("expectedStatus") == "failed":
                    outcome = "known-bug"
                entry = {"project": test["projectName"], "outcome": outcome, "bug": bug.group(1) if bug else None,
                         "title": title}  # fmt: skip
                for found in ID_RE.findall(title):
                    by_id[found].append(entry)
        for child in suite.get("suites", []):
            walk(child)

    for suite in data.get("suites", []):
        walk(suite)
    return by_id


def e2e_cell(results: list[dict]) -> tuple[str, str]:
    """(how tested, result) for the end-to-end part of a row."""
    if not results:
        return "", ""
    ran = [r for r in results if r["outcome"] != "skipped"]
    if not ran:
        return "E2E (skipped at every width)", "skipped"
    projects = len({r["project"] for r in ran})
    titles = sorted({ID_RE.sub("", r["title"]).strip() for r in ran})
    how = (
        f"E2E: {titles[0]}"
        + (f" (+{len(titles) - 1} more)" if len(titles) > 1 else "")
        + f" [{projects} runs]"
    )
    failed = [r for r in ran if r["outcome"] in ("unexpected", "flaky")]
    known = [r for r in ran if r["outcome"] == "known-bug"]
    if failed:
        return how, f"FAIL in {', '.join(sorted({r['project'] for r in failed}))}"
    if known:
        bugs = ", ".join(sorted({r["bug"] or "bug" for r in known}))
        return how, f"known bug {bugs} (test.fail)"
    return how, f"pass ({len(ran)}/{len(ran)})"


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_checklist(
    table: list[Row], e2e: dict[str, list[dict]], known_pytest: set[str]
) -> tuple[str, dict]:
    stats = Counter()
    lines = []
    gaps = []
    for row in table:
        how_parts, result_parts = [], []
        e2e_how, e2e_result = e2e_cell(e2e.get(row.id, []))
        if row.pytest:
            missing = [t for t in row.pytest if t not in known_pytest]
            assert not missing, f"{row.id} cites unknown pytest tests: {missing}"
            how_parts.append("pytest: " + ", ".join(row.pytest))
            result_parts.append("pass (pytest)")
        if e2e_how:
            how_parts.append(e2e_how)
            result_parts.append(e2e_result)
        automated = bool(row.pytest) or bool(e2e_how)
        if not automated:
            how_parts.append("manual")
            result_parts.append("not run")
            gaps.append(row)
        stats["automated" if automated else "manual"] += 1
        if any(r.startswith("FAIL") for r in result_parts):
            stats["failing"] += 1
        if any(r.startswith("known bug") for r in result_parts):
            stats["known_bug"] += 1
        if row.pytest and e2e_how:
            stats["both"] += 1
        elif e2e_how:
            stats["e2e_only"] += 1
        elif row.pytest:
            stats["pytest_only"] += 1
        lines.append(
            "| " + " | ".join(cell(x) for x in (row.id, row.page, row.role, row.feature, row.steps, row.normal,
                                                 row.weird, row.expected, "; ".join(how_parts), "; ".join(result_parts))) + " |"
        )  # fmt: skip
    return "\n".join(lines), {"stats": stats, "gaps": gaps}


def write_checklist() -> dict:
    table = rows()
    e2e = load_e2e()
    known = pytest_function_names()
    body, meta = render_checklist(table, e2e, known)
    stats, gaps = meta["stats"], meta["gaps"]
    functions, collected = count_pytest()
    ran_e2e = sum(len(v) for v in e2e.values()) > 0
    out = [
        "# Testing checklist",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} by `make e2e` (`python -m scripts.testing_report`) from "
        "`backend/scripts/testing_checklist.py` and Playwright's results. Do not edit by hand.",
        "",
        "## Summary",
        "",
        f"- Checklist items: **{len(table)}**",
        f"- Covered by at least one automated test: **{stats['automated']}** "
        f"({stats['pytest_only']} by pytest only, {stats['e2e_only']} by end-to-end tests only, "
        f"{stats['both']} by both)",
        f"- Not automated (manual): **{stats['manual']}**",
        f"- Items whose end-to-end test is a known bug (`test.fail`): **{stats['known_bug']}**",
        f"- Items whose end-to-end test currently fails: **{stats['failing']}**",
        f"- pytest: **{functions}** test functions, **{collected}** collected test cases. "
        "Cases outnumber functions because a parametrized test runs once per parameter.",
        ("" if ran_e2e else "- No end-to-end results were found; run `make e2e`."),
        "",
        "How to read the last column: `pass (pytest)` means the cited pytest tests passed in `make test`; "
        "`pass (n/n)` is the number of Playwright projects (Chromium 375, 768, 1280 and WebKit 1280) that "
        "ran the test and passed; `known bug BUG-n` means the E2E test is marked `test.fail()` because "
        "the bug in `docs/testing/bugs.md` is not fixed yet.",
        "",
        "| ID | Page | Role | Feature or button | Steps | Normal input | Weird inputs | Expected result | How tested | Result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        body,
        "",
        "## Gaps: items with no automated test",
        "",
    ]
    out += [f"- **{g.id}** {g.feature} ({g.page}, {g.role})" for g in gaps] or ["None."]
    out.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "checklist.md").write_text("\n".join(out))
    return {
        "items": len(table),
        **dict(stats),
        "pytest_functions": functions,
        "pytest_cases": collected,
    }


def write_a11y() -> dict:
    scans = (
        [json.loads(p.read_text()) for p in sorted(A11Y_DIR.glob("*.json"))]
        if A11Y_DIR.exists()
        else []
    )
    by_project: dict[str, Counter] = defaultdict(Counter)
    unique: dict[tuple[str, str], dict] = {}
    for scan in scans:
        for v in scan["violations"]:
            by_project[scan["project"]][v["impact"]] += 1
            key = (scan["url"], v["rule"])
            entry = unique.setdefault(
                key, {**v, "url": scan["url"], "roles": set(), "projects": set()}
            )
            entry["roles"].add(scan["role"])
            entry["projects"].add(scan["project"])
            entry["nodes"] = max(entry["nodes"], v["nodes"])
    severity = Counter(e["impact"] for e in unique.values())
    out = [
        "# Accessibility scan (axe-core)",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} from {len(scans)} scans (every page, per role, at "
        "375, 768 and 1280 px in Chromium and 1280 px in WebKit) with WCAG 2.0 and 2.1 A and AA rules "
        "plus axe best practices. Nothing is fixed yet; this is the starting list for the accessibility stage.",
        "",
        "## Violations by severity",
        "",
        "Unique violations: one per rule per page, counted once however many widths or roles show it.",
        "",
        "| Severity | Unique violations |",
        "| --- | --- |",
        *[f"| {s} | {severity.get(s, 0)} |" for s in SEVERITIES],
        f"| **Total** | **{sum(severity.values())}** |",
        "",
        "Per run (the same rule on the same page counts once per run):",
        "",
        "| Run | " + " | ".join(SEVERITIES) + " | Total |",
        "| --- | " + " | ".join("---" for _ in SEVERITIES) + " | --- |",
    ]
    for project, counts in sorted(by_project.items()):
        out.append(
            f"| {project} | "
            + " | ".join(str(counts.get(s, 0)) for s in SEVERITIES)
            + f" | {sum(counts.values())} |"
        )
    out += ["", "## Every unique violation", "", "| Severity | Rule | Page | What is wrong | Elements | Runs | Example |",
            "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    order = {s: i for i, s in enumerate(SEVERITIES)}
    for e in sorted(
        unique.values(), key=lambda e: (order.get(e["impact"], 9), e["rule"], e["url"])
    ):
        out.append(
            f"| {e['impact']} | `{e['rule']}` | {cell(e['url'])} | {cell(e['help'])} | {e['nodes']} | "
            f"{len(e['projects'])} | `{cell(e['example'][:90])}` |"
        )
    if not scans:
        out.append("| | No scans found; run `make e2e`. | | | | | |")
    out.append("")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "a11y-report.md").write_text("\n".join(out))
    return {"scans": len(scans), "unique": dict(severity), "total": sum(severity.values())}


def main() -> None:
    summary = write_checklist()
    a11y = write_a11y()
    print("Checklist:", json.dumps(summary))
    print("Accessibility:", json.dumps(a11y))


if __name__ == "__main__":
    main()
