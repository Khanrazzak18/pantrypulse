"""docs/security/checklist.md stays honest: every ticked measure cites proof that exists.

Proof is written in backticks after "proof:": a pytest test name (must exist), an end-to-end checklist
ID such as SEC-03 (must be a row in the testing checklist), a `make` target (must exist in the
Makefile), or a path in the repository (must exist).
"""

import re

from scripts.testing_checklist import rows
from scripts.testing_report import pytest_function_names
from tests.conftest import BACKEND_DIR

ROOT = BACKEND_DIR.parent
TEXT = (ROOT / "docs/security/checklist.md").read_text()
AREAS = [
    "Secrets",
    "AWS IAM",
    "Authentication and sessions",
    "Authorization",
    "Input validation",
    "SQL injection",
    "XSS and CSP",
    "CSRF",
    "Uploads",
    "Rate limits and cost",
    "Logging and privacy",
    "LLM and prompt injection",
    "Dependencies",
    "Data retention",
]


def measures_section() -> str:
    start = TEXT.index("## Measures in place")
    end = TEXT.index("\n## ", start + 1)
    return TEXT[start:end]


def ticked_lines() -> list[str]:
    return [line for line in measures_section().splitlines() if line.startswith("- [x]")]


def proofs(line: str) -> list[str]:
    assert "proof:" in line, f"no proof on: {line[:90]}"
    return re.findall(r"`([^`]+)`", line.split("proof:", 1)[1])


def makefile_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z0-9-]*):", (ROOT / "Makefile").read_text(), re.MULTILINE))


def test_every_one_of_the_fourteen_areas_has_a_heading_and_at_least_one_measure():
    section = measures_section()
    for area in AREAS:
        match = re.search(
            rf"^### {re.escape(area)}\n(.*?)(?=^### |\Z)", section, re.MULTILINE | re.DOTALL
        )
        assert match, f"missing area: {area}"
        assert "- [x]" in match.group(1), f"no ticked measure under: {area}"


def test_every_ticked_measure_names_its_proof_and_the_proof_exists():
    known_tests = pytest_function_names()
    checklist_ids = {r.id for r in rows()}
    targets = makefile_targets()
    lines = ticked_lines()
    assert len(lines) >= 50
    problems = []
    for line in lines:
        cited = proofs(line)
        if not cited:
            problems.append(f"empty proof: {line[:80]}")
        for token in cited:
            if token.startswith("test_"):
                ok = token in known_tests
            elif re.fullmatch(r"[A-Z0-9]+-\d{2}", token):
                ok = token in checklist_ids
            elif token.startswith("make "):
                ok = token.split()[1] in targets
            elif "/" in token or "." in token:
                ok = (ROOT / token.split()[0].rstrip(",")).exists()
            else:
                ok = False
            if not ok:
                problems.append(f"{token!r} in: {line[:80]}")
    assert problems == []


def test_the_two_accepted_risks_are_listed_with_their_rationale():
    section = TEXT[TEXT.index("## Accepted risks") :]
    assert "style-src" in section and "unsafe-inline" in section
    assert "braces" in section and "GHSA-vfj7-8cjw-p6xm" in section
    assert section.count("Revisit") >= 2
    assert "accepted-risks.json" in section


def test_the_pre_deploy_list_is_still_there():
    assert "## Before every deploy" in TEXT
    assert "make security" in TEXT.split("## Before every deploy")[1]


def test_no_secret_looking_value_is_in_the_checklist():
    assert not re.search(r"AKIA[0-9A-Z]{16}|-----BEGIN|ghp_[A-Za-z0-9]{20}", TEXT)
