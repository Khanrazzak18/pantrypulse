"""Fuzz every API endpoint: out-of-range ids, impossible dates, extreme numbers, huge text and
control characters in every path, query and body field, as a logged-out caller, a pantry manager
and an admin. Any HTTP 500 fails the test, and every error must be in the error envelope.

Skipped on purpose: the two slow jobs with no inputs (POST /api/forecasts/run and the weekly
refresh), and file uploads (covered separately below with hostile file names and contents).
"""

import json
from urllib.parse import quote

import pytest

from app.ai.llm_provider import LLMUnavailable
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("people", "allocation_world", "impact_world")

SKIP = {("POST", "/api/forecasts/run"), ("POST", "/api/admin/jobs/weekly-refresh")}
INTS = [
    "0",
    "-1",
    "2147483647",
    "2147483648",
    "99999999999999999999",
    "1.5",
    "abc",
    "1e400",
    "-99999999999999999999",
    "",
]
TEXTS = [
    "\u0000",
    "a\u0007b",
    "x" * 20000,
    "<script>alert(1)</script>",
    "' OR 1=1 --",
    "🥕" * 50,
    "%00",
    "../../etc/passwd",
    "a\r\nb",
    "   ",
]
DATES = [
    "0000-01-01",
    "0001-01-01",
    "9999-12-31",
    "2019-12-31",
    "2101-01-01",
    "2026-02-30",
    "99999-01-01",
    "2026-13-01",
    "0000-01",
    "9999-12",
]
HOSTILE_QUERY = INTS + TEXTS[:6] + DATES
JSON_VALUES = [
    None,
    True,
    [],
    {},
    "",
    0,
    -1,
    2**63,
    1e308,
    -1e308,
    1.5,
    "abc",
    *TEXTS,
    *DATES,
    [None],
    {"a": 1},
    [[]],
]


class Extracts:
    """A model that always reads the same valid manifest (for the upload tests)."""

    model_id = "fake"

    def converse_tool(self, **_):
        from app.ai.llm_provider import LLMResult
        from tests.fakes import extraction

        return LLMResult(extraction(), None, 10, 10, 5, "fake", "tool_use")


class AlwaysDown:
    """A model that is never reachable: routes must degrade, not crash."""

    model_id = "down"

    def converse_tool(self, **_):
        raise LLMUnavailable("down", retryable=False)


def resolve(schema, spec):
    if "$ref" in schema:
        node = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return resolve(node, spec)
    return schema


def sample(schema, spec, depth=0):
    """A plausible valid value for a schema (good enough to get past validation)."""
    schema = resolve(schema, spec)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"]
            return sample(options[0], spec, depth) if options else None
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {
            k: sample(v, spec, depth + 1)
            for k, v in schema.get("properties", {}).items()
            if k in schema.get("required", [])
        }
    if kind == "array":
        return [sample(schema.get("items", {}), spec, depth + 1)] if depth < 4 else []
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if schema.get("format") == "date":
        return "2026-10-05"
    return "x"


def leaf_paths(value, prefix=()):
    """Every (path) into a JSON value, one level of arrays and objects deep."""
    yield prefix
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaf_paths(v, (*prefix, k))
    elif isinstance(value, list) and value:
        yield from leaf_paths(value[0], (*prefix, 0))


def put(value, path, new):
    if not path:
        return new
    clone = json.loads(json.dumps(value))
    node = clone
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = new
    return clone


def requests_for(spec):
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            method = method.upper()
            if (method, path) in SKIP:
                continue
            params = [resolve(p, spec) for p in op.get("parameters", [])]
            path_params = [p for p in params if p["in"] == "path"]
            query_params = [p for p in params if p["in"] == "query"]
            good_path = path
            for p in path_params:
                good_path = good_path.replace(
                    "{" + p["name"] + "}", "2026-09" if "month" in p["name"] else "1"
                )
            good_query = {
                p["name"]: sample(p["schema"], spec) for p in query_params if p.get("required")
            }
            body = None
            content = op.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                body = sample(content["application/json"]["schema"], spec)
            elif content:
                continue  # multipart upload: covered separately
            # 1. hostile path parameters
            for p in path_params:
                for bad in [*INTS, *DATES, *TEXTS[:6]]:
                    yield (
                        method,
                        path.replace(
                            "{" + p["name"] + "}",
                            quote(bad, safe=""),
                        ),
                        good_query,
                        body,
                    )
            # 2. hostile query parameters
            for p in query_params:
                for bad in HOSTILE_QUERY:
                    yield method, good_path, {**good_query, p["name"]: bad}, body
            # 3. hostile JSON bodies
            if body is not None:
                for leaf in leaf_paths(body):
                    for bad in JSON_VALUES:
                        yield method, good_path, good_query, put(body, leaf, bad)
            yield method, good_path, good_query, body


def check(response, what):
    # 502, 503 and 504 are the documented answers when the AI or database is away; 500 is a bug.
    assert response.status_code != 500, f"{what} -> 500: {response.text[:200]}"
    if response.status_code >= 400:
        body = response.json()
        assert set(body) == {"error"} and {"code", "message", "details", "request_id"} <= set(
            body["error"]
        ), what


def fuzz(client):
    spec = client.app.openapi()
    sent = 0
    for method, path, query, body in requests_for(spec):
        try:
            payload = json.dumps(body, allow_nan=False) if body is not None else None
        except ValueError:
            continue
        response = client.request(
            method, path, params=query, content=payload, headers={"content-type": "application/json"} if payload else {},
        )  # fmt: skip
        check(response, f"{method} {path} {str(query)[:80]} {str(payload)[:80]}")
        sent += 1
    return sent


@pytest.fixture
def fuzz_app(client):
    client.app.state.llm = AlwaysDown()
    return client


def test_the_fuzzer_covers_a_lot_of_ground(fuzz_app):
    count = sum(1 for _ in requests_for(fuzz_app.app.openapi()))
    assert count > 1500


def test_fuzz_as_an_admin(fuzz_app, people):
    login(fuzz_app, people.admin)
    assert fuzz(fuzz_app) > 1500


def test_fuzz_as_a_pantry_manager(fuzz_app, people):
    login(fuzz_app, people.manager)
    assert fuzz(fuzz_app) > 1500


def test_fuzz_logged_out(fuzz_app):
    assert fuzz(fuzz_app) > 1500


@pytest.mark.parametrize(
    "name",
    [
        "a\u0000b.txt",
        "a\u0007b.txt",
        "x" * 5000 + ".txt",
        "<script>.txt",
        "../../etc/passwd.txt",
        "🥕.txt",
        ".txt",
        "..",
        "a/b\\c.eml",
    ],
)
def test_fuzz_upload_file_names(fuzz_app, people, name):
    fuzz_app.app.state.llm = Extracts()
    login(fuzz_app, people.admin)
    response = fuzz_app.post(
        "/api/donations", files={"file": (name, b"10 cases of lettuce", "text/plain")}
    )
    check(response, f"upload {name[:30]!r}")


@pytest.mark.parametrize(
    "content",
    [
        b"\x00" * 2000,
        b"\xff\xfe\xfd" * 500,
        b"a\x00b" * 100,
        ("x" * 200000).encode(),
        b"%PDF-" + b"\x00" * 100,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
    ],
)
@pytest.mark.parametrize("ext", ["txt", "eml", "pdf", "png", "jpg", "webp"])
def test_fuzz_upload_file_contents(fuzz_app, people, content, ext):
    fuzz_app.app.state.llm = Extracts()
    login(fuzz_app, people.admin)
    response = fuzz_app.post(
        "/api/donations", files={"file": (f"f.{ext}", content, "application/octet-stream")}
    )
    check(response, f"upload content as .{ext}")
