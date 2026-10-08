"""Field-level scoring for the intake eval: what counts as a correct field."""

import pytest

from eval.scoring import (
    FIELDS,
    aggregate,
    donor_matches,
    match_items,
    name_matches,
    normalize_unit,
    score_case,
)


def exp(**kw):
    base = {"name": "Chicken thighs", "category": "protein", "quantity": 10, "unit": "case",
            "estimated_weight_lbs": 400.0, "expiry_date": "2026-10-14", "storage_type": "refrigerated"}  # fmt: skip
    return {**base, **kw}


def case(items, donor="Greenfield Market", fmt="email", cid="001"):
    return {"id": cid, "format": fmt, "donor_name": donor, "items": items}


def actual(items, donor="Greenfield Market"):
    return {"donor_name": donor, "items": items}


# --- names -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "got"),
    [
        ("Chicken thighs", "chicken thighs"),
        ("Chicken thighs", "Boneless chicken thighs"),
        ("Whole milk", "milk, whole"),
        ("Gala apples", "Apples"),
        ("Romaine lettuce", "romaine lettuces"),
        ("Frozen meals", "Frozen Meal"),
    ],
)
def test_names_that_mean_the_same_thing_match(expected, got):
    assert name_matches(expected, got)


@pytest.mark.parametrize(
    ("expected", "got"),
    [
        ("Chicken thighs", "Ground beef"),
        ("Canned corn", "Green beans"),
        ("Whole milk", "Cheddar cheese"),
    ],
)
def test_different_foods_do_not_match(expected, got):
    assert not name_matches(expected, got)


@pytest.mark.parametrize(
    ("raw", "normal"),
    [("lbs", "lb"), ("Pounds", "lb"), ("cases", "case"), ("CS", "case"), ("kgs", "kg"),
     ("boxes", "box"), ("pallets", "pallet"), ("gal", "gallon"), ("dozens", "dozen"), ("ea", "each")],
)  # fmt: skip
def test_units_are_normalised(raw, normal):
    assert normalize_unit(raw) == normal


@pytest.mark.parametrize(
    ("expected", "got", "ok"),
    [("Greenfield Market", "greenfield market inc.", True), ("Greenfield Market", "Greenfield Market, LLC", True),
     ("Harbor Foods", "Harbour Foods", False), ("Harbor Foods", None, False), (None, None, True),
     ("Greenfield Market", "The Greenfield Market", True)],
)  # fmt: skip
def test_donor_names_ignore_case_punctuation_and_company_suffixes(expected, got, ok):
    assert donor_matches(expected, got) is ok


# --- items ---------------------------------------------------------------------------------------


def test_a_perfect_answer_scores_100_percent():
    result = score_case(case([exp()]), actual([exp()]))
    assert result.correct == result.total == len(FIELDS) == 7
    assert result.missed == 0 and result.extra == 0 and result.donor_correct


def test_each_wrong_field_costs_exactly_one():
    wrong = exp(category="dairy", unit="box", storage_type="frozen", expiry_date=None)
    result = score_case(case([exp()]), actual([wrong]))
    assert (result.correct, result.total) == (3, 7)
    wrong_fields = {f for f, ok in result.items[0].fields.items() if not ok}
    assert wrong_fields == {"category", "unit", "storage_type", "expiry_date"}


@pytest.mark.parametrize(
    ("got", "ok"),
    [(400.0, True), (419.0, True), (381.0, True), (421.0, False), (379.0, False), (0.0, False)],
)
def test_weights_must_be_within_5_percent(got, ok):
    result = score_case(case([exp()]), actual([exp(estimated_weight_lbs=got)]))
    assert result.items[0].fields["estimated_weight_lbs"] is ok


@pytest.mark.parametrize(("got", "ok"), [(10, True), (10.05, True), (11, False), (9, False)])
def test_quantities_must_be_essentially_exact(got, ok):
    assert score_case(case([exp()]), actual([exp(quantity=got)])).items[0].fields["quantity"] is ok


def test_a_missing_expiry_is_correct_only_when_none_was_expected():
    none_expected = score_case(case([exp(expiry_date=None)]), actual([exp(expiry_date=None)]))
    assert none_expected.items[0].fields["expiry_date"]
    invented = score_case(case([exp(expiry_date=None)]), actual([exp(expiry_date="2026-10-14")]))
    assert not invented.items[0].fields["expiry_date"]
    missed = score_case(case([exp()]), actual([exp(expiry_date=None)]))
    assert not missed.items[0].fields["expiry_date"]


def test_a_missed_item_costs_all_seven_fields():
    result = score_case(case([exp(), exp(name="Eggs", category="dairy")]), actual([exp()]))
    assert (result.correct, result.total, result.missed) == (7, 14, 1)


def test_extra_items_are_counted_separately_and_do_not_lower_field_accuracy():
    result = score_case(
        case([exp()]), actual([exp(), exp(name="Paper towels", category="dry_goods")])
    )
    assert (result.correct, result.total, result.extra) == (7, 7, 1)


def test_items_are_matched_regardless_of_order():
    a, b = (
        exp(),
        exp(name="Eggs", category="dairy", unit="dozen", quantity=20, estimated_weight_lbs=30),
    )
    result = score_case(case([a, b]), actual([b, a]))
    assert result.correct == result.total == 14


def test_two_lines_with_the_same_name_pair_off_one_to_one():
    a = exp(name="Apples", quantity=5, estimated_weight_lbs=150)
    b = exp(name="Apples", quantity=8, estimated_weight_lbs=240)
    result = score_case(case([a, b]), actual([b, a]))
    assert result.correct == result.total == 14 and result.extra == 0


def test_a_completely_different_item_is_a_miss_plus_an_extra():
    pairs, extras = match_items([exp()], [exp(name="Paper towels")])
    assert pairs == [(0, None)] and extras == [0]


def test_a_failed_extraction_scores_zero():
    result = score_case(case([exp(), exp(name="Eggs")]), None)
    assert (result.correct, result.total, result.missed) == (0, 14, 2) and result.failed


# --- aggregation -------------------------------------------------------------------------------


def test_aggregate_reports_overall_per_field_and_per_format_accuracy():
    good = score_case(case([exp()], fmt="email", cid="001"), actual([exp()]))
    half = score_case(
        case([exp()], fmt="pdf", cid="002"), actual([exp(category="dairy", unit="box")])
    )
    summary = aggregate([good, half])
    assert summary.correct == 12 and summary.total == 14
    assert summary.accuracy == pytest.approx(12 / 14)
    assert summary.by_field["category"] == (1, 2) and summary.by_field["name"] == (2, 2)
    assert summary.by_format["email"] == (7, 7) and summary.by_format["pdf"] == (5, 7)
    assert summary.cases == 2 and summary.failed_cases == 0 and summary.items_expected == 2
    assert summary.item_recall == 1.0


def test_aggregate_counts_failed_cases_and_missed_items():
    ok = score_case(case([exp()]), actual([exp()]))
    failed = score_case(case([exp()], cid="002"), None)
    summary = aggregate([ok, failed])
    assert summary.failed_cases == 1 and summary.items_missed == 1 and summary.item_recall == 0.5
    assert summary.accuracy == 0.5


# --- accepted names (a food may be printed under several names) ----------------------------------


def with_names(**kw):
    return exp(
        name="Shelf-stable milk", category="beverages", unit="case",
        accepted_names=["Shelf-stable milk", "UHT milk"], **kw,
    )  # fmt: skip


def test_any_accepted_name_counts_as_the_right_name():
    expected = with_names()
    result = score_case(case([expected]), actual([dict(expected, name="UHT milk")]))
    assert result.items[0].fields["name"] and result.missed == 0 and result.extra == 0


def test_without_accepted_names_only_the_name_itself_counts():
    expected = exp(name="Shelf-stable milk", category="beverages")
    result = score_case(case([expected]), actual([dict(expected, name="UHT milk")]))
    assert result.missed == 1 and result.extra == 1  # (the old, stricter behaviour)


def test_a_different_food_is_still_wrong_even_when_names_are_accepted():
    expected = with_names()
    result = score_case(case([expected]), actual([dict(expected, name="Cheddar cheese")]))
    assert result.missed == 1 and result.extra == 1


def test_pairing_uses_the_best_accepted_name():
    pairs, extras = match_items([with_names()], [exp(name="uht milk", category="beverages")])
    assert pairs == [(0, 0)] and extras == []
