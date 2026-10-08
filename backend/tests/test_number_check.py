from app.services.number_check import numbers_in, unsupported_numbers


def test_numbers_are_found_with_commas_and_decimals():
    assert numbers_in("Sent 1,234 lb, spoilage 12.5%, 3 pantries") == [1234.0, 12.5, 3.0]


def test_numbers_that_are_in_the_facts_pass():
    assert unsupported_numbers("12.5% of 1,234 lb", {12.5, 1234.0}) == []


def test_large_numbers_allow_rounding_by_one_and_small_ones_do_not():
    assert unsupported_numbers("about 1,235 lb", {1234.0}) == []
    assert unsupported_numbers("1,240 lb", {1234.0}) == [1240.0]
    assert unsupported_numbers("7.5%", {7.0}) == [7.5]
    assert unsupported_numbers("7.04", {7.0}) == []


def test_invented_numbers_are_returned():
    assert unsupported_numbers("served 500 and 20 households", {500.0}) == [20.0]
