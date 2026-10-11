"""The minimum AWS permission the app needs, kept in the repository and checked against the code."""

import json
import re

from tests.conftest import BACKEND_DIR

ROOT = BACKEND_DIR.parent
POLICY = json.loads((ROOT / "docs/security/iam-policy.json").read_text())


def statements():
    return POLICY["Statement"]


def test_the_policy_allows_exactly_one_action_and_nothing_with_a_wildcard_action():
    actions = []
    for s in statements():
        assert s["Effect"] == "Allow"
        actions += [s["Action"]] if isinstance(s["Action"], str) else s["Action"]
    assert actions == ["bedrock:InvokeModel"]


def test_the_resources_are_only_the_haiku_inference_profile_and_its_foundation_models():
    resources = [
        r
        for s in statements()
        for r in (s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]])
    ]
    assert "*" not in resources
    assert all("claude-haiku-4-5-20251001" in r for r in resources)
    assert any(":inference-profile/us.anthropic." in r for r in resources)
    assert any("::foundation-model/anthropic." in r for r in resources)


def test_the_model_the_app_is_configured_for_is_the_one_the_policy_allows():
    example = (ROOT / ".env.example").read_text()
    model = re.search(r"^BEDROCK_MODEL_ID=(\S+)", example, re.MULTILINE).group(1)
    policy_text = json.dumps(POLICY)
    assert model in policy_text
    assert model.removeprefix("us.") in policy_text


def test_the_app_calls_no_bedrock_api_other_than_converse():
    # converse is authorised by bedrock:InvokeModel; anything else would need more permission
    calls = set()
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        calls |= set(
            re.findall(
                r"\.(converse_stream|invoke_model\w*|list_\w+|get_\w+_profile|get_foundation_model)\(",
                path.read_text(),
            )
        )
    assert calls == set()
    assert ".converse(" in (BACKEND_DIR / "app/ai/llm_provider.py").read_text()
