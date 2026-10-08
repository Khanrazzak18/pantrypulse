"""Test doubles. Tests never talk to Bedrock: they script a FakeLLM instead."""

from app.ai.llm_provider import LLMResult


class FakeLLM:
    """Stands in for BedrockProvider. Script its replies, then inspect `calls`.

    A scripted reply can be a dict (the tool input the model "returned"), a str (a text-only
    reply with no tool call), an LLMResult, or an Exception instance (raised).
    """

    model_id = "fake-model"

    def __init__(self):
        self.outputs: list = []
        self.calls: list[dict] = []

    def script(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []
        return self

    def converse_tool(self, *, system, content, tool_name, tool_description, input_schema,
                      max_tokens=4096):  # fmt: skip
        self.calls.append(
            {"system": system, "content": content, "tool_name": tool_name, "schema": input_schema}
        )
        if not self.outputs:
            raise AssertionError("FakeLLM was called more times than it was scripted for")
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, LLMResult):
            return out
        if isinstance(out, str):
            return LLMResult(None, out, 100, 20, 900, self.model_id, "end_turn")
        return LLMResult(out, None, 1200, 340, 1850, self.model_id, "tool_use")


def confidence(**overrides) -> dict:
    base = {
        k: 0.95
        for k in ("name", "category", "quantity", "unit", "estimated_weight_lbs",
                  "expiry_date", "storage_type")
    }  # fmt: skip
    return {**base, **overrides}


def item(**overrides) -> dict:
    base = {
        "name": "Chicken thighs",
        "category": "protein",
        "quantity": 10,
        "unit": "case",
        "estimated_weight_lbs": 400,
        "expiry_date": "2099-01-15",
        "storage_type": "refrigerated",
        "confidence": confidence(),
    }
    return {**base, **overrides}


def extraction(items=None, donor="Greenfield Market", notes=None) -> dict:
    return {
        "donor_name": donor,
        "items": [item()] if items is None else items,
        "notes": notes,
    }
