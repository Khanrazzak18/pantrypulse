"""Validated types shared by every API boundary, so each id, date and piece of text is checked in
one place: ids must fit the database, dates must be 2020 to 2100, and text may not carry control
characters (a NUL character, for example, cannot be stored by Postgres and used to cause a 500).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Annotated

from fastapi import Path
from pydantic import AfterValidator, Field

MAX_ID = 2_147_483_647  # the largest value of a Postgres integer column
MIN_DATE = date(2020, 1, 1)
MAX_DATE = date(2100, 12, 31)
DATE_MESSAGE = "Dates must be between 2020 and 2100."
MONTH_MESSAGE = "The month must be between 2020-01 and 2100-12 (format YYYY-MM)."
CONTROL_MESSAGE = "Text can't contain control characters."
LINE_MESSAGE = "Text must be on one line and can't contain control characters."
_MONTH = re.compile(r"^(20[2-9]\d|2100)-(0[1-9]|1[0-2])$")
_BLOCK_OK = {"\n", "\t", "\r"}


def check_date(value: date) -> date:
    if not MIN_DATE <= value <= MAX_DATE:
        raise ValueError(DATE_MESSAGE)
    return value


def check_month(value: str) -> str:
    if not _MONTH.match(value):
        raise ValueError(MONTH_MESSAGE)
    return value


def _has_control(text: str, allowed: set[str]) -> bool:
    return any(unicodedata.category(c) == "Cc" and c not in allowed for c in text)


def has_control(text: str) -> bool:
    """True if the text has any control character, including a new line."""
    return _has_control(text, set())


def check_line(value: str) -> str:
    if _has_control(value, set()):
        raise ValueError(LINE_MESSAGE)
    return value


def check_block(value: str) -> str:
    if _has_control(value, _BLOCK_OK):
        raise ValueError(CONTROL_MESSAGE)
    return value


def strip_controls(value: str, keep_newlines: bool = False) -> str:
    """Remove control characters from text we did not get from a person (the model's output)."""
    allowed = _BLOCK_OK if keep_newlines else set()
    return "".join(c for c in value if not (unicodedata.category(c) == "Cc" and c not in allowed))


def scrub(value):
    """`strip_controls` for every string inside JSON-like data (Postgres JSONB cannot hold NUL)."""
    if isinstance(value, str):
        return strip_controls(value, keep_newlines=True)
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


PositiveId = Annotated[int, Field(ge=1, le=MAX_ID)]
SafeDate = Annotated[date, AfterValidator(check_date)]
Month = Annotated[str, AfterValidator(check_month)]
LineText = Annotated[str, AfterValidator(check_line)]
BlockText = Annotated[str, AfterValidator(check_block)]

# For URL paths: an id outside this range is a 404 (the record cannot exist), see errors.py.
PathId = Annotated[int, Path(ge=1, le=MAX_ID)]
