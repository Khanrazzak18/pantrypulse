"""What the model is asked to return. The tool's JSON schema is generated from these models."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import CATEGORY_NAMES, STORAGE_TYPES

Category = Literal[*CATEGORY_NAMES]
StorageType = Literal[*STORAGE_TYPES]


class FieldConfidence(BaseModel):
    """0 to 1 for each field. Fields under 0.8 are highlighted for the reviewer."""

    name: float = Field(ge=0, le=1)
    category: float = Field(ge=0, le=1)
    quantity: float = Field(ge=0, le=1)
    unit: float = Field(ge=0, le=1)
    estimated_weight_lbs: float = Field(ge=0, le=1)
    expiry_date: float = Field(ge=0, le=1)
    storage_type: float = Field(ge=0, le=1)


class ExtractedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200, description="What the food is, in plain words")
    category: Category = Field(description="The type of food (not its temperature)")
    quantity: float = Field(gt=0, le=1_000_000, description="Number of units, as stated")
    unit: str = Field(min_length=1, max_length=30, description="Singular lowercase unit")
    estimated_weight_lbs: float = Field(
        gt=0, le=100_000, description="Total weight of the whole line in pounds"
    )
    expiry_date: date | None = Field(description="YYYY-MM-DD, or null if the manifest gives none")
    storage_type: StorageType = Field(description="The temperature it must be kept at")
    confidence: FieldConfidence

    @field_validator("name", "unit", mode="before")
    @classmethod
    def _tidy(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("unit")
    @classmethod
    def _lowercase_unit(cls, value: str) -> str:
        return value.lower()


class DonationExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    donor_name: str | None = Field(default=None, description="The donating organization, or null")
    items: list[ExtractedItem] = Field(max_length=100)
    notes: str | None = Field(default=None, description="One short note for the coordinator")

    @field_validator("donor_name", mode="after")
    @classmethod
    def _clip_donor(cls, value: str | None) -> str | None:
        value = value.strip()[:120] if value else None
        return value or None

    @field_validator("notes", mode="after")
    @classmethod
    def _clip_notes(cls, value: str | None) -> str | None:
        value = value.strip()[:500] if value else None
        return value or None


def _inline_refs(schema: dict) -> dict:
    """Resolve $ref/$defs and drop titles and defaults: every model reads plain schemas best."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {
                k: resolve(v) for k, v in node.items() if k not in ("title", "$defs", "default")
            }
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def tool_input_schema() -> dict:
    return _inline_refs(DonationExtraction.model_json_schema())
