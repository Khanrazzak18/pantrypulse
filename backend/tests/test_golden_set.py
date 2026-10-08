"""The golden set is the eval's ground truth: check it is complete, valid and reproducible."""

import json
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from app.constants import CATEGORY_NAMES, STORAGE_TYPES
from app.services import intake
from eval import make_golden_set as golden

ROOT = golden.GOLDEN_DIR
CASES = sorted(p for p in ROOT.iterdir() if p.is_dir()) if ROOT.exists() else []


def expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text())


def test_there_are_50_cases_split_30_15_5():
    assert len(CASES) == 50
    formats = Counter(expected(c)["format"] for c in CASES)
    assert formats == {"email": 30, "pdf": 15, "image": 5}


def test_every_case_has_one_manifest_with_the_right_extension():
    for case_dir in CASES:
        spec = expected(case_dir)
        files = [p for p in case_dir.iterdir() if p.name != "expected.json"]
        assert [p.name for p in files] == [spec["file"]], case_dir.name
        suffix = files[0].suffix
        assert suffix == {"email": ".eml", "pdf": ".pdf", "image": suffix}[spec["format"]]
        if spec["format"] == "image":
            assert suffix in (".png", ".jpg")


def test_expected_files_are_well_formed():
    ids = set()
    for case_dir in CASES:
        spec = expected(case_dir)
        assert spec["id"] == case_dir.name and spec["id"] not in ids
        ids.add(spec["id"])
        assert spec["received_date"] == "2026-10-05"
        assert spec["items"], case_dir.name
        for it in spec["items"]:
            assert it["category"] in CATEGORY_NAMES and it["storage_type"] in STORAGE_TYPES
            assert it["quantity"] > 0 and it["estimated_weight_lbs"] > 0
            assert it["name"] and it["unit"]
            names = it["accepted_names"]
            assert it["name"] in names and len({n.lower() for n in names}) == len(names)
            assert it["expiry_date"] is None or len(it["expiry_date"]) == 10


def test_every_manifest_passes_the_apps_own_upload_validation():
    for case_dir in CASES:
        spec = expected(case_dir)
        path = case_dir / spec["file"]
        prepared = intake.prepare_upload(path.name, path.read_bytes())
        assert prepared.kind in ("email", "pdf", "image")
        if prepared.kind == "image":
            assert prepared.model_bytes and len(prepared.model_bytes) <= intake.MAX_IMAGE_BYTES
        if prepared.kind == "pdf":
            assert len(prepared.data) <= intake.MAX_PDF_BYTES


def test_pdfs_and_images_are_real_files():
    for case_dir in CASES:
        spec = expected(case_dir)
        path = case_dir / spec["file"]
        if spec["format"] == "pdf":
            assert path.read_bytes().startswith(b"%PDF-")
        if spec["format"] == "image":
            with Image.open(path) as image:
                assert image.size[0] >= 800 and image.size[1] >= 800


def test_the_set_covers_the_hard_cases():
    tags = Counter(t for c in CASES for t in expected(c)["tags"])
    required = {"frozen_protein": 3, "frozen_meal": 3, "frozen_produce": 3, "kg": 3, "pallet": 3,
                "relative_date": 4, "month_year_date": 3, "injection": 3, "non_food": 3,
                "not_donated": 2, "no_date": 3}  # fmt: skip
    for tag, minimum in required.items():
        assert tags[tag] >= minimum, f"{tag}: {tags[tag]} < {minimum}"


def test_the_rule_cases_have_the_right_expected_answers():
    items = [it for c in CASES for it in expected(c)["items"]]
    frozen_protein = [
        i for i in items if i["category"] == "protein" and i["storage_type"] == "frozen"
    ]
    frozen_meals = [i for i in items if i["category"] == "frozen"]
    frozen_veg = [i for i in items if i["category"] == "produce" and i["storage_type"] == "frozen"]
    assert frozen_protein and frozen_meals and frozen_veg
    assert all(i["storage_type"] == "frozen" for i in frozen_meals)


def test_the_committed_set_matches_what_the_generator_produces():
    built = {c.id: c for c in golden.build_cases()}
    assert set(built) == {c.name for c in CASES}
    for case_dir in CASES:
        assert expected(case_dir) == built[case_dir.name].expected_json()
        if expected(case_dir)["format"] == "email":  # text is renderer-independent
            assert (case_dir / expected(case_dir)["file"]).read_bytes() == built[
                case_dir.name
            ].email_bytes()


def test_generation_is_deterministic():
    first = [c.expected_json() for c in golden.build_cases()]
    second = [c.expected_json() for c in golden.build_cases()]
    assert first == second
    assert first != [c.expected_json() for c in golden.build_cases(seed=golden.SEED + 1)]


@pytest.mark.parametrize(
    ("category", "unit", "qty", "stated", "weight"),
    [("protein", "case", 10, None, 400.0), ("produce", "case", 3, None, 90.0),
     ("bakery", "box", 4, None, 72.0), ("dry_goods", "bag", 4, 25.0, 100.0),
     ("dairy", "gallon", 10, None, 86.0), ("dairy", "dozen", 20, None, 30.0),
     ("produce", "pallet", 2, None, 2000.0), ("protein", "kg", 100, None, 220.5),
     ("canned", "lb", 55, None, 55.0), ("canned", "case", 5, 30.0, 150.0)],
)  # fmt: skip
def test_expected_weights_follow_the_rules_in_the_prompt(category, unit, qty, stated, weight):
    assert golden.expected_weight(category, unit, qty, stated) == pytest.approx(weight, abs=0.1)
