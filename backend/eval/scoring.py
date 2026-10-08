"""Field-level scoring for the intake eval.

Each expected item has seven fields (name, category, quantity, unit, estimated weight, expiry
date, storage type). A field is correct if the model's matching item has an equivalent value:

- name: the same food after ignoring case, plurals and filler words (one name contains the other,
  or at least half the words are shared). A food can be printed under several names (UHT milk or
  shelf-stable milk, popsicles or ice pops), so the expected answer lists every accepted name;
- category, storage type, expiry date: equal (a missing expiry is correct only if none was expected);
- unit: equal after normalising plurals and abbreviations (lbs -> lb, cs -> case, ...);
- quantity: within 1%;
- estimated weight: within 5%.

An expected item the model did not find counts as seven wrong fields. Extra items the model
invented are counted and reported, but do not change field accuracy.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

FIELDS = (
    "name",
    "category",
    "quantity",
    "unit",
    "estimated_weight_lbs",
    "expiry_date",
    "storage_type",
)
PAIRING_THRESHOLD = 0.3
NAME_MATCH_THRESHOLD = 0.5

_FILLER = {"fresh", "assorted", "of", "the", "and", "a", "an", "bagged", "boxed", "pack", "mixed"}
_COMPANY_WORDS = {"inc", "llc", "ltd", "co", "corp", "company", "the"}
_UNIT_ALIASES = {
    "lbs": "lb", "pound": "lb", "pounds": "lb", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "cs": "case", "cases": "case", "boxes": "box", "bags": "bag", "pallets": "pallet",
    "gal": "gallon", "gallons": "gallon", "dozens": "dozen", "doz": "dozen", "ea": "each",
    "ounce": "oz", "ounces": "oz", "cans": "can", "jars": "jar", "bottles": "bottle",
    "loaves": "loaf", "packs": "pack", "packages": "package",
}  # fmt: skip


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("oes", "ces", "ses", "xes")):
        return word[:-1] if word.endswith("ces") else word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words if w not in _FILLER}


def name_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    if ta <= tb or tb <= ta:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def name_matches(expected: str, got: str) -> bool:
    return name_similarity(expected, got) >= NAME_MATCH_THRESHOLD


def _names(expected: dict) -> list[str]:
    """Every name that counts as correct for this food (a manifest may print any of them)."""
    return expected.get("accepted_names") or [expected["name"]]


def best_name_similarity(expected: dict, got: str) -> float:
    return max(name_similarity(name, got) for name in _names(expected))


def normalize_unit(unit: str | None) -> str:
    unit = (unit or "").strip().lower().rstrip(".")
    return _UNIT_ALIASES.get(unit, unit)


def donor_matches(expected: str | None, got: str | None) -> bool:
    if expected is None or got is None:
        return expected is None and got is None

    def words(name: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in _COMPANY_WORDS}

    return words(expected) == words(got)


def _field_checks(expected: dict, got: dict) -> dict[str, bool]:
    weight = float(expected["estimated_weight_lbs"])
    return {
        "name": best_name_similarity(expected, str(got.get("name", ""))) >= NAME_MATCH_THRESHOLD,
        "category": expected["category"] == got.get("category"),
        "quantity": math.isclose(
            float(expected["quantity"]), float(got.get("quantity") or 0), rel_tol=0.01, abs_tol=0.01
        ),
        "unit": normalize_unit(expected["unit"]) == normalize_unit(got.get("unit")),
        "estimated_weight_lbs": abs(float(got.get("estimated_weight_lbs") or 0) - weight)
        <= max(0.05 * weight, 0.5),
        "expiry_date": expected.get("expiry_date") == got.get("expiry_date"),
        "storage_type": expected["storage_type"] == got.get("storage_type"),
    }


def match_items(
    expected: list[dict], got: list[dict]
) -> tuple[list[tuple[int, int | None]], list[int]]:
    """Pair each expected item with at most one of the model's items (best name match first,
    ties broken by how many other fields agree). Returns (pairs in expected order, extras)."""
    candidates = []
    for i, e in enumerate(expected):
        for j, g in enumerate(got):
            similarity = best_name_similarity(e, str(g.get("name", "")))
            if similarity >= PAIRING_THRESHOLD:
                others = sum(ok for f, ok in _field_checks(e, g).items() if f != "name")
                candidates.append((-similarity, -others, i, j))
    taken_expected: dict[int, int] = {}
    taken_got: set[int] = set()
    for _, _, i, j in sorted(candidates):
        if i not in taken_expected and j not in taken_got:
            taken_expected[i] = j
            taken_got.add(j)
    pairs = [(i, taken_expected.get(i)) for i in range(len(expected))]
    extras = [j for j in range(len(got)) if j not in taken_got]
    return pairs, extras


@dataclass
class ItemScore:
    expected: dict
    got: dict | None
    fields: dict[str, bool]


@dataclass
class CaseScore:
    case_id: str
    format: str
    items: list[ItemScore] = field(default_factory=list)
    correct: int = 0
    total: int = 0
    missed: int = 0
    extra: int = 0
    donor_correct: bool = False
    failed: bool = False


def score_case(case: dict, actual: dict | None) -> CaseScore:
    expected_items = case["items"]
    score = CaseScore(case["id"], case["format"], total=len(FIELDS) * len(expected_items))
    if actual is None:
        score.failed = True
        score.missed = len(expected_items)
        score.items = [ItemScore(e, None, dict.fromkeys(FIELDS, False)) for e in expected_items]
        return score
    got_items = actual.get("items", [])
    pairs, extras = match_items(expected_items, got_items)
    for i, j in pairs:
        if j is None:
            score.missed += 1
            score.items.append(ItemScore(expected_items[i], None, dict.fromkeys(FIELDS, False)))
        else:
            fields = _field_checks(expected_items[i], got_items[j])
            score.correct += sum(fields.values())
            score.items.append(ItemScore(expected_items[i], got_items[j], fields))
    score.extra = len(extras)
    score.donor_correct = donor_matches(case.get("donor_name"), actual.get("donor_name"))
    return score


@dataclass
class Summary:
    cases: int
    correct: int
    total: int
    by_field: dict[str, tuple[int, int]]
    by_format: dict[str, tuple[int, int]]
    failed_cases: int
    items_expected: int
    items_missed: int
    extra_items: int
    donors_correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def item_recall(self) -> float:
        found = self.items_expected - self.items_missed
        return found / self.items_expected if self.items_expected else 0.0


def aggregate(scores: list[CaseScore]) -> Summary:
    by_field = {f: [0, 0] for f in FIELDS}
    by_format: dict[str, list[int]] = {}
    for s in scores:
        bucket = by_format.setdefault(s.format, [0, 0])
        bucket[0] += s.correct
        bucket[1] += s.total
        for item in s.items:
            for f, ok in item.fields.items():
                by_field[f][0] += int(ok)
                by_field[f][1] += 1
    return Summary(
        cases=len(scores),
        correct=sum(s.correct for s in scores),
        total=sum(s.total for s in scores),
        by_field={f: (c, t) for f, (c, t) in by_field.items()},
        by_format={f: (c, t) for f, (c, t) in by_format.items()},
        failed_cases=sum(s.failed for s in scores),
        items_expected=sum(len(s.items) for s in scores),
        items_missed=sum(s.missed for s in scores),
        extra_items=sum(s.extra for s in scores),
        donors_correct=sum(s.donor_correct for s in scores),
    )
