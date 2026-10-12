"""The data-driven tables in docs/testing/report.md: row status, grouping by role and page, markers."""

from scripts import testing_report as tr
from scripts.testing_checklist import Row


def row(id_, page="/x", role="Coordinator", pytest=()):
    return Row(id_, page, role, "f", "s", "n", "w", "e", tuple(pytest))


PASS = {"project": "chromium-1280", "outcome": "expected", "bug": None, "title": "[A-01] t"}
FAIL = {**PASS, "outcome": "unexpected"}
SKIP = {**PASS, "outcome": "skipped"}
KNOWN = {**PASS, "outcome": "known-bug", "bug": "BUG-1"}


def test_a_row_passes_when_every_automated_part_passes():
    known = {"test_a"}
    assert tr.row_status(row("A-01", pytest=["test_a"]), {}, known) == "pass"
    assert tr.row_status(row("A-01"), {"A-01": [PASS]}, set()) == "pass"
    assert tr.row_status(row("A-01", pytest=["test_a"]), {"A-01": [PASS]}, known) == "pass"


def test_a_failing_or_known_bug_or_manual_row_is_named_as_such():
    assert tr.row_status(row("A-01"), {"A-01": [PASS, FAIL]}, set()) == "FAIL"
    assert tr.row_status(row("A-01"), {"A-01": [KNOWN]}, set()) == "known bug"
    assert tr.row_status(row("A-01"), {}, set()) == "manual"
    assert tr.row_status(row("A-01"), {"A-01": [SKIP]}, set()) == "skipped"


def test_rows_are_counted_under_every_role_they_name():
    table = [
        row("A-01", role="Coordinator, Admin"),
        row("A-02", role="Admin"),
        row("A-03", role="All"),
    ]
    by_role = tr.group_status(
        table, {"A-01": [PASS], "A-02": [FAIL], "A-03": [PASS]}, set(), "role"
    )
    assert by_role["Admin"] == {"pass": 1, "FAIL": 1}
    assert by_role["Coordinator"] == {"pass": 1}
    assert by_role["All"] == {"pass": 1}


def test_rows_are_grouped_by_their_page():
    table = [row("A-01", page="/a"), row("A-02", page="/a"), row("A-03", page="/b")]
    by_page = tr.group_status(
        table, {"A-01": [PASS], "A-02": [PASS], "A-03": [PASS]}, set(), "page"
    )
    assert by_page["/a"] == {"pass": 2}
    assert by_page["/b"] == {"pass": 1}


def test_the_markdown_table_has_a_total_row_and_a_pass_column():
    md = tr.status_table({"X": {"pass": 3, "FAIL": 1}, "Y": {"pass": 2}}, "Role")
    lines = md.splitlines()
    assert lines[0].startswith("| Role | Items | Passing |")
    assert "| X | 4 | 3 |" in md and "| Y | 2 | 2 |" in md
    assert lines[-1].startswith("| **Total** | **6** | **5** |")


def test_replacing_a_marked_block_keeps_the_text_around_it():
    text = "before\n<!-- GENERATED:t -->\nold\n<!-- /GENERATED:t -->\nafter\n"
    out = tr.replace_block(text, "t", "new")
    assert out == "before\n<!-- GENERATED:t -->\nnew\n<!-- /GENERATED:t -->\nafter\n"
    assert tr.replace_block("no markers here", "t", "new") == "no markers here"


def test_e2e_runs_are_counted_by_project_and_outcome():
    counts = tr.count_runs([PASS, SKIP, FAIL, {**PASS, "project": "webkit-1280"}, KNOWN])
    assert counts["chromium-1280"] == {"passed": 2, "skipped": 1, "failed": 1}
    assert counts["webkit-1280"] == {"passed": 1}


def test_the_report_lists_exactly_the_bugs_in_the_bug_log_and_has_its_generated_blocks():
    import re

    from tests.conftest import BACKEND_DIR

    docs = BACKEND_DIR.parent / "docs/testing"
    report = (docs / "report.md").read_text()
    log = (docs / "bugs.md").read_text()
    in_log = set(re.findall(r"^\| (BUG-\d+) \|", log, re.MULTILINE))
    in_report = set(re.findall(r"^\| (BUG-\d+) \|", report, re.MULTILINE))
    assert in_log == in_report and len(in_log) == 23
    for block in ("counts", "by-role", "by-page"):
        assert f"<!-- GENERATED:{block} -->" in report and f"<!-- /GENERATED:{block} -->" in report
