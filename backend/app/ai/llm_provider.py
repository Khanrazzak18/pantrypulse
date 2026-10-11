"""Amazon Bedrock through the Converse API, behind a small interface the app (and tests) share.

Credentials come from the AWS CLI profile in AWS_PROFILE; no keys are ever read from .env.
The provider makes one attempt per call. `run_with_retry` owns the retry policy so that a
timeout and an invalid answer share one budget: at most one retry in total.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    ProfileNotFound,
    ReadTimeoutError,
)

from app.config import Settings

logger = logging.getLogger("pantrypulse.llm")

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 45
MAX_OUTPUT_TOKENS = 4096  # the most any single call may ask for (cost cap)
MAX_READ_TIMEOUT_SECONDS = 60  # the longest any single call may wait

_sleep = time.sleep  # tests replace this so backoff does not slow them down


# --- errors -----------------------------------------------------------------------------------


class LLMError(Exception):
    """A failed model call. `retryable` says whether trying again could help."""

    retryable = False


class LLMTimeout(LLMError):
    retryable = True


class LLMThrottled(LLMError):
    retryable = True


class LLMUnavailable(LLMError):
    def __init__(self, message: str = "", retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class LLMAccessDenied(LLMError):
    """Missing credentials or permissions. Retrying cannot fix this."""


class LLMBadRequest(LLMError):
    """The request itself was rejected (bad model ID, input too large, ...)."""


class LLMNotConfigured(LLMError):
    """BEDROCK_MODEL_ID is not set."""


class InvalidModelOutput(LLMError):
    """The model answered, but not with usable data. The next attempt is told why."""

    retryable = True


# --- results and interface --------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResult:
    tool_input: dict[str, Any] | None
    text: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model_id: str
    stop_reason: str


class LLMProvider(Protocol):
    model_id: str

    def converse_tool(
        self,
        *,
        system: str,
        content: list[dict],
        tool_name: str,
        tool_description: str,
        input_schema: dict,
        max_tokens: int = MAX_OUTPUT_TOKENS,
        timeout_seconds: float | None = None,
    ) -> LLMResult: ...


# --- Bedrock ----------------------------------------------------------------------------------

_CLIENT_ERROR_MAP: dict[str, tuple[type[LLMError], bool]] = {
    "ModelTimeoutException": (LLMTimeout, True),
    "ThrottlingException": (LLMThrottled, True),
    "TooManyRequestsException": (LLMThrottled, True),
    "ServiceUnavailableException": (LLMUnavailable, True),
    "InternalServerException": (LLMUnavailable, True),
    "ModelNotReadyException": (LLMUnavailable, True),
    "AccessDeniedException": (LLMAccessDenied, False),
    "UnrecognizedClientException": (LLMAccessDenied, False),
    "ExpiredTokenException": (LLMAccessDenied, False),
    "ValidationException": (LLMBadRequest, False),
    "ResourceNotFoundException": (LLMBadRequest, False),
}


class BedrockProvider:
    def __init__(self, settings: Settings, client=None, session_factory=None):
        self._settings = settings
        self._client = client
        self._injected = client is not None  # tests pass a fake; it serves every timeout
        self._timeout_clients: dict[float, object] = {}
        self._session_factory = session_factory
        self.model_id = settings.bedrock_model_id

    def _build_client(self, read_timeout: float):
        factory = self._session_factory or boto3.Session
        session = factory(
            profile_name=self._settings.aws_profile, region_name=self._settings.aws_region
        )
        return session.client(
            "bedrock-runtime",
            config=Config(
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                read_timeout=read_timeout,
                retries={"total_max_attempts": 1},  # retries are ours (run_with_retry)
            ),
        )

    def _get_client(self, read_timeout: float | None = None):
        """Built on first use, so the app starts without AWS access. A call that asks for its own
        timeout gets its own client (one per distinct timeout)."""
        if self._injected:
            return self._client
        if read_timeout is None:
            if self._client is None:
                self._client = self._build_client(READ_TIMEOUT_SECONDS)
            return self._client
        if read_timeout not in self._timeout_clients:
            self._timeout_clients[read_timeout] = self._build_client(read_timeout)
        return self._timeout_clients[read_timeout]

    def converse_tool(
        self,
        *,
        system: str,
        content: list[dict],
        tool_name: str,
        tool_description: str,
        input_schema: dict,
        max_tokens: int = MAX_OUTPUT_TOKENS,
        timeout_seconds: float | None = None,
    ) -> LLMResult:
        if not self.model_id:
            raise LLMNotConfigured("BEDROCK_MODEL_ID is not set in .env")
        # Whatever a caller asks for, one call can never cost more than these limits.
        max_tokens = max(1, min(max_tokens, MAX_OUTPUT_TOKENS))
        if timeout_seconds is not None:
            timeout_seconds = max(1.0, min(timeout_seconds, MAX_READ_TIMEOUT_SECONDS))
        request = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": content}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool_name,
                            "description": tool_description,
                            "inputSchema": {"json": input_schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": tool_name}},  # the model must call this tool
            },
        }
        start = time.perf_counter()
        try:
            response = self._get_client(timeout_seconds).converse(**request)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            error = self._translate(exc)
            self._log(latency_ms, 0, 0, self._outcome(exc), "error")
            raise error from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = response.get("usage", {})
        input_tokens = int(usage.get("inputTokens", 0))
        output_tokens = int(usage.get("outputTokens", 0))
        stop_reason = response.get("stopReason", "")
        self._log(latency_ms, input_tokens, output_tokens, "ok", stop_reason)

        tool_input, texts = None, []
        for block in response.get("output", {}).get("message", {}).get("content", []):
            if "toolUse" in block and block["toolUse"].get("name") == tool_name:
                tool_input = block["toolUse"].get("input")
            elif "text" in block:
                texts.append(block["text"])
        return LLMResult(
            tool_input=tool_input,
            text="\n".join(texts) or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            model_id=self.model_id,
            stop_reason=stop_reason,
        )

    # -- helpers --

    def _log(self, latency_ms, input_tokens, output_tokens, outcome, stop_reason) -> None:
        # Never log the prompt or the manifest: only model, timing, token counts and outcome.
        logger.info(
            "llm_call",
            extra={
                "model_id": self.model_id,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "outcome": outcome,
                "stop_reason": stop_reason,
            },
        )

    @staticmethod
    def _outcome(exc: Exception) -> str:
        if isinstance(exc, ClientError):
            return exc.response.get("Error", {}).get("Code", "ClientError")
        return type(exc).__name__

    @staticmethod
    def _translate(exc: Exception) -> LLMError:
        if isinstance(exc, (ReadTimeoutError, ConnectTimeoutError)):
            return LLMTimeout("The model call timed out")
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            kind, retryable = _CLIENT_ERROR_MAP.get(code, (LLMUnavailable, False))
            if kind is LLMUnavailable:
                return LLMUnavailable(f"Bedrock error {code or 'unknown'}", retryable=retryable)
            return kind(f"Bedrock error {code}")
        if isinstance(exc, (NoCredentialsError, PartialCredentialsError, ProfileNotFound)):
            return LLMAccessDenied("AWS credentials are missing or the profile was not found")
        if isinstance(exc, NoRegionError):
            return LLMNotConfigured("AWS_REGION is not set")
        if isinstance(exc, (EndpointConnectionError, ConnectionClosedError)):
            return LLMUnavailable("Could not reach Bedrock", retryable=True)
        return LLMUnavailable(f"Unexpected error: {type(exc).__name__}", retryable=False)


# --- retry policy -----------------------------------------------------------------------------


@dataclass
class RetryOutcome[T]:
    value: T
    result: LLMResult
    attempts: int
    input_tokens: int  # totals over every attempt that returned an answer, rejected ones included
    output_tokens: int


def run_with_retry[T](
    call: Callable[[str | None], LLMResult],
    validate: Callable[[LLMResult], T],
    *,
    max_attempts: int = 2,
    backoff_seconds: float = 1.0,
) -> RetryOutcome[T]:
    """Call the model and validate its answer, retrying once.

    `call` receives a hint describing why the previous answer was rejected (None on the first
    attempt). Timeouts, throttling, 5xx errors and invalid answers all draw on the same budget,
    so the model is called at most `max_attempts` times in total.
    """
    hint: str | None = None
    last: LLMError | None = None
    tokens_in = tokens_out = 0
    for attempt in range(1, max_attempts + 1):
        try:
            result = call(hint)
            tokens_in += result.input_tokens
            tokens_out += result.output_tokens
            return RetryOutcome(validate(result), result, attempt, tokens_in, tokens_out)
        except InvalidModelOutput as exc:
            last = exc
            hint = f"Your previous answer was rejected because: {exc}. Answer again and fix that."
        except LLMError as exc:
            if not exc.retryable:
                raise
            last = exc
        if attempt < max_attempts:
            # jitter for the retry delay, not a security use of randomness
            _sleep(backoff_seconds * 2 ** (attempt - 1) + random.uniform(0, 0.25))  # nosec B311
    if last is None:  # cannot happen: the loop ran at least once
        raise RuntimeError("run_with_retry made no attempt")
    raise last
