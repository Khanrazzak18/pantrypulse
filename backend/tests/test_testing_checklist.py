"""The testing checklist stays honest: unique IDs, real pytest references, E2E titles that cite real rows."""

import re
from collections import Counter

from scripts.testing_checklist import rows
from scripts.testing_report import ID_RE, pytest_function_names
from tests.conftest import BACKEND_DIR

E2E_DIR = BACKEND_DIR.parent / "frontend/e2e"


def test_checklist_ids_are_unique_and_rows_are_complete():
    table = rows()
    assert len(table) >= 150
    ids = [r.id for r in table]
    assert [i for i, n in Counter(ids).items() if n > 1] == []
    for row in table:
        assert re.fullmatch(r"[A-Z0-9]+-\d{2}", row.id), row.id
        assert all(
            [row.page, row.role, row.feature, row.steps, row.normal, row.weird, row.expected]
        )


def test_every_cited_pytest_test_exists():
    known = pytest_function_names()
    missing = {r.id: [t for t in r.pytest if t not in known] for r in rows()}
    assert {k: v for k, v in missing.items() if v} == {}


def test_every_end_to_end_test_cites_a_real_checklist_row():
    ids = {r.id for r in rows()}
    cited = set()
    for path in E2E_DIR.glob("*.spec.ts"):
        for title in re.findall(r"test\(\s*[`\"']([^`\"']+)", path.read_text()):
            found = ID_RE.findall(title)
            if (
                "${" in title
            ):  # a templated title: its IDs are listed as "XX-01" strings in the file
                found = re.findall(r'"((?!BUG)[A-Z0-9]+-\d{2})"', path.read_text())
            assert found, f"{path.name}: test without a checklist ID: {title}"
            cited |= {i for i in found if not i.startswith("BUG-")}
    assert cited - ids == set()
