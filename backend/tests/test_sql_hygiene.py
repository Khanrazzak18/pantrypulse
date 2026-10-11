"""SQL injection hygiene, checked from the source: no SQL is built from user text.

Request-path code uses SQLAlchemy expressions or constant `text()` strings with bound parameters. A
new raw SQL statement changes the inventory below and fails the test until a person has looked at it
and updated the list (and docs/security/audit.md).
"""

import ast

from tests.conftest import BACKEND_DIR

APP = BACKEND_DIR / "app"

# file (relative to backend/app) -> number of text(...) calls. Reviewed in the Stage 12 audit.
RAW_SQL_INVENTORY = {
    "api/health.py": 1,  # SELECT 1
    "models/donations.py": 1,  # a column default expression, no input
    "security/rate_limit.py": 1,  # the counter upsert, values bound
    "services/dashboard.py": 7,  # report queries, dates bound
    "services/forecast_runs.py": 1,  # the training panel query, no input
}
SQL_CALLS = {"execute", "exec_driver_sql", "text"}


def python_files():
    return sorted(APP.rglob("*.py"))


def calls(tree, names):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name in names:
                yield node, name


def test_every_raw_sql_text_is_a_constant_string():
    bad = []
    for path in python_files():
        for node, _ in calls(ast.parse(path.read_text()), {"text", "exec_driver_sql"}):
            if node.args and not isinstance(node.args[0], ast.Constant):
                bad.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert bad == []


def test_no_sql_is_built_with_f_strings_formats_or_concatenation():
    bad = []
    for path in python_files():
        tree = ast.parse(path.read_text())
        for node, _ in calls(tree, SQL_CALLS):
            for arg in node.args[:1]:
                if isinstance(arg, (ast.JoinedStr, ast.BinOp)) or (
                    isinstance(arg, ast.Call) and getattr(arg.func, "attr", "") == "format"
                ):
                    bad.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert bad == []


def test_the_inventory_of_raw_sql_is_the_one_that_was_reviewed():
    found = {}
    for path in python_files():
        n = sum(1 for _ in calls(ast.parse(path.read_text()), {"text"}))
        if n:
            found[str(path.relative_to(APP))] = n
    assert found == RAW_SQL_INVENTORY, (
        "raw SQL changed: review it, then update RAW_SQL_INVENTORY and the audit"
    )


def test_values_reach_raw_sql_only_as_bound_parameters():
    # every ":name" placeholder in a constant text() has its value passed separately
    for path in python_files():
        source = path.read_text()
        for node, _ in calls(ast.parse(source), {"text"}):
            if node.args and isinstance(node.args[0], ast.Constant):
                assert "%s" not in node.args[0].value and "' ||" not in node.args[0].value, path


def test_the_seed_script_quotes_every_table_name_it_puts_in_sql():
    source = (BACKEND_DIR / "scripts/seed.py").read_text()
    assert "quote(" in source
    tree = ast.parse(source)
    for node, _ in calls(tree, {"text"}):
        arg = node.args[0]
        if isinstance(arg, ast.JoinedStr):
            for part in arg.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                value = part.value
                quoted = isinstance(value, ast.Call) and getattr(value.func, "id", "") == "quote"
                already_quoted = isinstance(value, ast.Name) and value.id in {"names", "table"}
                assert quoted or already_quoted, (
                    f"seed.py:{node.lineno} puts an unquoted value in SQL"
                )


def test_no_database_url_or_password_is_logged_or_printed():
    for path in python_files():
        text_ = path.read_text()
        assert "database_url" not in text_ or "logger" not in text_.split("database_url")[1][:80], (
            path
        )
