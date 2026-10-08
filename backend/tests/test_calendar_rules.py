"""School-holiday and benefit-week rules. They stand in for real school and benefit calendars:
the generator used them to build history, and the forecast uses them for weeks that have not
happened yet."""

from datetime import date, timedelta

import pytest

from app.constants import COUNTIES
from app.services.calendar_rules import benefit_week, school_holiday
from scripts.generate_synthetic_data import DEFAULT_SEED, generate


def test_summer_break_is_a_school_holiday():
    assert school_holiday("Brookmere", date(2026, 7, 6))


def test_a_normal_autumn_week_is_not():
    assert not school_holiday("Ashford", date(2026, 10, 5))


def test_thanksgiving_week_and_winter_break_are_holidays_everywhere():
    for county in COUNTIES:
        assert school_holiday(county, date(2026, 11, 23))  # week containing Thanksgiving
        assert school_holiday(county, date(2026, 12, 28))


def test_counties_start_summer_break_in_different_weeks():
    week = date(2026, 6, 8)
    assert school_holiday("Ashford", week)  # starts a week earlier
    assert not school_holiday("Brookmere", week)


def test_benefit_week_is_the_week_containing_the_countys_issue_day():
    assert benefit_week("Ashford", date(2026, 9, 28))  # Oct 1 falls in this week
    assert not benefit_week("Ashford", date(2026, 10, 5))
    assert benefit_week("Brookmere", date(2026, 9, 28))  # issue day 3: Oct 3
    assert benefit_week("Dunmore", date(2026, 10, 5))  # issue day 10: Oct 10


def test_each_county_has_about_one_benefit_week_a_month():
    weeks = [date(2026, 1, 5) + timedelta(weeks=i) for i in range(52)]
    for county in COUNTIES:
        count = sum(benefit_week(county, w) for w in weeks)
        assert 11 <= count <= 13


def test_unknown_counties_are_an_error():
    with pytest.raises(ValueError, match="Atlantis"):
        school_holiday("Atlantis", date(2026, 10, 5))
    with pytest.raises(ValueError, match="Atlantis"):
        benefit_week("Atlantis", date(2026, 10, 5))


def test_the_generated_history_uses_exactly_these_rules():
    for row in generate(DEFAULT_SEED).weekly_context[::7]:
        assert row["school_holiday"] == school_holiday(row["county"], row["week_start"])
        assert row["benefit_week"] == benefit_week(row["county"], row["week_start"])
