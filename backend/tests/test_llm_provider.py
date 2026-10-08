import io
import json
import logging

import pytest
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)

from app.ai import llm_provider
from app.ai.llm_provider import (
    BedrockProvider,
    LLMAccessDenied,
    LLMBadRequest,
    LLMNotConfigured,
    LLMThrottled,
    LLMTimeout,
    LLMUnavailable,
)
from app.logging import JsonFormatter

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
SCHEMA = {"type": "object", "properties": {"items": {"type": "array"}}}
TOOL = "record_donation_items"


class FakeClient:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def tool_reply(tool_input=None, tokens=(1200, 340), stop="tool_use"):
    return {
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t1", "name": TOOL, "input": tool_input or {"items": []}}}
        ]}},
        "stopReason": stop,
        "usage": {"inputTokens": tokens[0], "outputTokens": tokens[1], "totalTokens": sum(tokens)},
    }  # fmt: skip


def client_error(code, message="boom"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "Converse")


@pytest.fixture
def provider_for(settings):
    def make(*replies, model=MODEL):
        client = FakeClient(*replies)
        cfg = settings.model_copy(update={"bedrock_model_id": model})
        return BedrockProvider(cfg, client=client), client

    return make


def call(provider, content=None):
    return provider.converse_tool(
        system="You extract donations.",
        content=content or [{"text": "hello"}],
        tool_name=TOOL,
        tool_description="Record the items",
        input_schema=SCHEMA,
    )


def test_request_forces_the_tool_and_uses_the_configured_model(provider_for):
    provider, client = provider_for(tool_reply())
    call(provider, [{"text": "manifest"}])
    request = client.requests[0]
    assert request["modelId"] == MODEL
    assert request["system"] == [{"text": "You extract donations."}]
    assert request["messages"] == [{"role": "user", "content": [{"text": "manifest"}]}]
    assert request["inferenceConfig"]["temperature"] == 0
    assert request["inferenceConfig"]["maxTokens"] >= 1024
    tool_config = request["toolConfig"]
    assert tool_config["toolChoice"] == {"tool": {"name": TOOL}}
    spec = tool_config["tools"][0]["toolSpec"]
    assert spec["name"] == TOOL and spec["inputSchema"] == {"json": SCHEMA}


@pytest.mark.parametrize(
    "block",
    [
        {"text": "plain text"},
        {"document": {"format": "pdf", "name": "manifest", "source": {"bytes": b"%PDF-1"}}},
        {"image": {"format": "png", "source": {"bytes": b"\x89PNG"}}},
    ],
    ids=["text", "pdf document", "image"],
)
def test_text_pdf_and_image_blocks_are_passed_through_unchanged(provider_for, block):
    provider, client = provider_for(tool_reply())
    call(provider, [block, {"text": "extract"}])
    assert client.requests[0]["messages"][0]["content"][0] == block


def test_the_tool_input_usage_latency_and_model_are_returned(provider_for):
    provider, _ = provider_for(tool_reply({"items": [1]}, tokens=(321, 45)))
    result = call(provider)
    assert result.tool_input == {"items": [1]}
    assert (result.input_tokens, result.output_tokens) == (321, 45)
    assert result.model_id == MODEL and result.stop_reason == "tool_use"
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0


def test_a_reply_without_a_tool_call_returns_its_text_and_no_tool_input(provider_for):
    reply = {
        "output": {"message": {"role": "assistant", "content": [{"text": "I cannot do that."}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 50, "outputTokens": 6},
    }
    provider, _ = provider_for(reply)
    result = call(provider)
    assert result.tool_input is None and result.text == "I cannot do that."


def case(raised, expected, retryable, name):
    return pytest.param(raised, expected, retryable, id=name)


@pytest.mark.parametrize(
    ("raised", "expected", "retryable"),
    [
        case(ReadTimeoutError(endpoint_url="https://x"), LLMTimeout, True, "read timeout"),
        case(ConnectTimeoutError(endpoint_url="https://x"), LLMTimeout, True, "connect timeout"),
        case(client_error("ModelTimeoutException"), LLMTimeout, True, "model timeout"),
        case(client_error("ThrottlingException"), LLMThrottled, True, "throttled"),
        case(client_error("ServiceUnavailableException"), LLMUnavailable, True, "unavailable"),
        case(client_error("InternalServerException"), LLMUnavailable, True, "server error"),
        case(EndpointConnectionError(endpoint_url="https://x"), LLMUnavailable, True, "no route"),
        case(client_error("AccessDeniedException"), LLMAccessDenied, False, "access denied"),
        case(client_error("ExpiredTokenException"), LLMAccessDenied, False, "expired token"),
        case(NoCredentialsError(), LLMAccessDenied, False, "no credentials"),
        case(client_error("ValidationException"), LLMBadRequest, False, "validation"),
        case(client_error("ResourceNotFoundException"), LLMBadRequest, False, "not found"),
        case(client_error("SomethingNew"), LLMUnavailable, False, "unknown code"),
    ],
)
def test_aws_errors_become_typed_errors_with_the_right_retry_flag(
    provider_for, raised, expected, retryable
):
    provider, _ = provider_for(raised)
    with pytest.raises(expected) as exc:
        call(provider)
    assert exc.value.retryable is retryable


def test_an_unset_model_id_is_reported_as_not_configured_without_calling_aws(provider_for):
    provider, client = provider_for(model="")
    with pytest.raises(LLMNotConfigured, match="BEDROCK_MODEL_ID"):
        call(provider)
    assert client.requests == []


def test_the_boto_client_is_built_lazily_from_the_profile_region_and_timeouts(settings):
    seen = {}

    class Session:
        def __init__(self, **kwargs):
            seen["session"] = kwargs

        def client(self, name, **kwargs):
            seen["client"] = (name, kwargs)
            return FakeClient(tool_reply())

    cfg = settings.model_copy(
        update={"bedrock_model_id": MODEL, "aws_profile": "pantrypulse", "aws_region": "us-east-1"}
    )
    provider = BedrockProvider(cfg, session_factory=Session)
    assert seen == {}  # nothing built yet: the app can start without AWS
    call(provider)
    assert seen["session"] == {"profile_name": "pantrypulse", "region_name": "us-east-1"}
    name, kwargs = seen["client"]
    assert name == "bedrock-runtime"
    boto_config = kwargs["config"]
    assert boto_config.connect_timeout == 5 and boto_config.read_timeout == 45
    assert boto_config.retries["total_max_attempts"] == 1  # we own the retry policy


@pytest.fixture
def llm_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("pantrypulse")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield lambda: [json.loads(x) for x in stream.getvalue().splitlines() if x.strip()]
    logger.removeHandler(handler)


def test_a_successful_call_logs_model_latency_and_token_counts(provider_for, llm_logs):
    provider, _ = provider_for(tool_reply(tokens=(777, 88)))
    call(provider, [{"text": "SECRET-MANIFEST-TEXT"}])
    entry = next(e for e in llm_logs() if e["message"] == "llm_call")
    assert entry["model_id"] == MODEL
    assert entry["input_tokens"] == 777 and entry["output_tokens"] == 88
    assert entry["outcome"] == "ok" and isinstance(entry["latency_ms"], int)


def test_a_failed_call_logs_the_error_code_and_never_the_manifest(provider_for, llm_logs):
    provider, _ = provider_for(client_error("ThrottlingException", "Too many requests"))
    with pytest.raises(LLMThrottled):
        call(provider, [{"text": "SECRET-MANIFEST-TEXT"}])
    entries = llm_logs()
    entry = next(e for e in entries if e["message"] == "llm_call")
    assert entry["outcome"] == "ThrottlingException" and entry["model_id"] == MODEL
    assert "SECRET-MANIFEST-TEXT" not in json.dumps(entries)


def test_sleep_is_a_module_level_hook():
    assert callable(llm_provider._sleep)
