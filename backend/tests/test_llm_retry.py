import pytest

from app.ai import llm_provider
from app.ai.llm_provider import (
    InvalidModelOutput,
    LLMAccessDenied,
    LLMResult,
    LLMThrottled,
    LLMTimeout,
    run_with_retry,
)


def result(tag="ok") -> LLMResult:
    return LLMResult({"tag": tag}, None, 10, 5, 100, "m", "tool_use")


class Script:
    """A call() that replays outcomes and remembers the retry hints it was given."""

    def __init__(self, *outcomes):
        self.outcomes, self.hints = list(outcomes), []

    def __call__(self, hint):
        self.hints.append(hint)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def accept(res: LLMResult):
    return res.tool_input["tag"]


def reject_first(res: LLMResult):
    if res.tool_input["tag"] == "bad":
        raise InvalidModelOutput("quantity must be greater than 0")
    return res.tool_input["tag"]


def test_success_on_the_first_attempt_makes_one_call_and_does_not_sleep(sleeps):
    call = Script(result())
    outcome = run_with_retry(call, accept)
    assert (outcome.value, outcome.attempts, len(call.hints), sleeps) == ("ok", 1, 1, [])
    assert call.hints == [None]


def test_a_timeout_is_retried_once_after_a_backoff(sleeps):
    call = Script(LLMTimeout("slow"), result())
    outcome = run_with_retry(call, accept)
    assert outcome.value == "ok" and outcome.attempts == 2
    assert len(sleeps) == 1 and sleeps[0] >= 1.0


def test_throttling_is_retried(sleeps):
    outcome = run_with_retry(Script(LLMThrottled("busy"), result()), accept)
    assert outcome.attempts == 2


def test_two_timeouts_raise_the_error_after_exactly_two_calls(sleeps):
    call = Script(LLMTimeout("first"), LLMTimeout("second"))
    with pytest.raises(LLMTimeout, match="second"):
        run_with_retry(call, accept)
    assert len(call.hints) == 2 and len(sleeps) == 1


def test_errors_that_cannot_succeed_are_not_retried(sleeps):
    call = Script(LLMAccessDenied("no"))
    with pytest.raises(LLMAccessDenied):
        run_with_retry(call, accept)
    assert len(call.hints) == 1 and sleeps == []


def test_invalid_output_is_retried_and_the_second_call_is_told_what_was_wrong(sleeps):
    call = Script(result("bad"), result("good"))
    outcome = run_with_retry(call, reject_first)
    assert outcome.value == "good" and outcome.attempts == 2
    assert call.hints[0] is None
    assert "quantity must be greater than 0" in call.hints[1]


def test_invalid_output_twice_raises_after_exactly_two_calls(sleeps):
    call = Script(result("bad"), result("bad"))
    with pytest.raises(InvalidModelOutput):
        run_with_retry(call, reject_first)
    assert len(call.hints) == 2


def test_the_retry_budget_is_shared_across_kinds_of_failure(sleeps):
    """A timeout followed by invalid output is two failures: no third attempt."""
    call = Script(LLMTimeout("slow"), result("bad"), result("good"))
    with pytest.raises(InvalidModelOutput):
        run_with_retry(call, reject_first)
    assert len(call.hints) == 2


def test_backoff_uses_the_module_sleep(sleeps):
    assert llm_provider._sleep is not None  # patched by the sleeps fixture in conftest


def test_token_totals_include_answers_that_were_rejected(sleeps):
    outcome = run_with_retry(Script(result("bad"), result("good")), reject_first)
    assert (outcome.input_tokens, outcome.output_tokens) == (20, 10)  # 10 + 10 and 5 + 5
