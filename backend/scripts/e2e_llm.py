"""A scripted stand-in for Bedrock, used ONLY by the end-to-end test server.

The server is `scripts/e2e_server.py`.

It answers the three tool calls the app makes (intake, allocation reasons, monthly summary) with
canned but valid output, and can be told to misbehave so the error states can be exercised. Nothing
under `app/` imports this module; `tests/test_e2e_isolation.py` enforces that.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

from app.ai.llm_provider import LLMResult, LLMTimeout, LLMUnavailable

MODEL_ID = "e2e-mock-model"
MODES = ("ok", "down", "bad_numbers")


class MockLLM:
    model_id = MODEL_ID

    def __init__(self, today: date):
        self.today = today
        self.mode = "ok"
        self.calls: list[str] = []

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode

    def converse_tool(self, *, system, content, tool_name, tool_description, input_schema,
                      max_tokens=4096, timeout_seconds=None):  # fmt: skip
        self.calls.append(tool_name)
        text = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
        if self.mode == "down":
            raise LLMUnavailable("The mock AI is switched off", retryable=False)
        if "E2E_SLOW" in text:
            time.sleep(4)  # long enough to press Cancel
        if "E2E_TIMEOUT" in text:
            raise LLMTimeout("The mock AI timed out")
        if tool_name == "record_donation_items":
            payload = self._items(text)
        elif tool_name == "record_reasons":
            payload = self._reasons(text)
        elif tool_name == "record_summary":
            payload = self._summary(text)
        else:
            raise AssertionError(f"unexpected tool {tool_name}")
        return LLMResult(payload, None, 900, 300, 40, MODEL_ID, "tool_use")

    # --- intake ---------------------------------------------------------------------------
    def _items(self, text: str) -> dict:
        def conf(**low):
            fields = ("name", "category", "quantity", "unit", "estimated_weight_lbs",
                      "expiry_date", "storage_type")  # fmt: skip
            base = {k: 0.95 for k in fields}
            return {**base, **low}

        soon = (self.today + timedelta(days=8)).isoformat()
        if "E2E_EMPTY" in text:
            return {"donor_name": "Mock Market", "items": [], "notes": "Nothing donated"}
        return {
            "donor_name": "Mock Market",
            "items": [
                {"name": "Romaine lettuce", "category": "produce", "quantity": 10, "unit": "case",
                 "estimated_weight_lbs": 300, "expiry_date": soon, "storage_type": "refrigerated",
                 "confidence": conf(storage_type=0.6)},
                {"name": "2% milk", "category": "dairy", "quantity": 5, "unit": "case",
                 "estimated_weight_lbs": 120, "expiry_date": soon, "storage_type": "refrigerated",
                 "confidence": conf()},
                {"name": "Canned corn", "category": "canned", "quantity": 20, "unit": "case",
                 "estimated_weight_lbs": 560, "expiry_date": None, "storage_type": "ambient",
                 "confidence": conf()},
            ],
            "notes": None,
        }  # fmt: skip

    # --- allocation reasons ---------------------------------------------------------------
    def _reasons(self, text: str) -> dict:
        if "E2E_NO_REASONS" in text:
            raise LLMTimeout("slow")
        start = text.index("[")
        facts = json.JSONDecoder().raw_decode(text[start:])[0]
        return {
            "reasons": [
                {
                    "id": f["id"],
                    "reason": f"{f['pantry']}: forecast need {f['forecast_lbs']} lb "
                    f"{f['category']}, {f['miles']:g} miles away",
                }
                for f in facts
            ]
        }

    # --- monthly summary ------------------------------------------------------------------
    def _summary(self, text: str) -> dict:
        start = text.index("{")
        facts = json.JSONDecoder().raw_decode(text[start:])[0]
        lbs, households = facts["pounds_distributed"], facts["households_served"]
        if self.mode == "bad_numbers":
            invented = lbs + 12345
            return {
                "summary": f"Partner pantries received {invented:,} pounds and served "
                f"{households:,} households this month, a record for the food bank."
            }
        return {
            "summary": f"In {facts['month_label']} partner pantries distributed {lbs:,} pounds of "
            f"food and served {households:,} households. Spoilage of perishable food was "
            f"{facts['spoilage_pct']}%."
        }
