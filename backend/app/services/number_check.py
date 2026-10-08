"""The check that stops a model from inventing numbers.

Used for allocation reasons and for the AI monthly summary: every number in the model's text must
be one of the numbers it was given, give or take rounding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
LARGE = 20  # from here a number may be rounded by up to 1; below it only by 0.06


def numbers_in(text: str) -> list[float]:
    found = (m.replace(",", "") for m in _NUMBER.findall(text))
    return [float(n) for n in found if n]


def is_supported(number: float, allowed: Iterable[float]) -> bool:
    tolerance = 1.0 if number >= LARGE else 0.06
    return any(abs(number - a) <= tolerance for a in allowed)


def unsupported_numbers(text: str, allowed: Iterable[float]) -> list[float]:
    """The numbers in `text` that are not (within rounding) one of `allowed`."""
    allowed = list(allowed)
    return [n for n in numbers_in(text) if not is_supported(n, allowed)]
