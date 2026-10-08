"""School-holiday and benefit-payment weeks.

These are synthetic stand-ins for real school calendars and benefit-issuance schedules. Both
are known well in advance, which is why the forecast may use them for a week that has not
happened yet. The data generator used the same rules to build the history.
"""

from datetime import date, timedelta

from app.constants import COUNTIES

COUNTY_NAMES = list(COUNTIES)
# Day of the month benefits are issued, by county.
BENEFIT_DAY = dict(zip(COUNTY_NAMES, [1, 3, 5, 10, 12, 15], strict=True))


def _county_index(county: str) -> int:
    try:
        return COUNTY_NAMES.index(county)
    except ValueError:
        raise ValueError(f"Unknown county: {county!r}") from None


def thanksgiving(year: int) -> date:
    first = date(year, 11, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + timedelta(weeks=3)


def school_holiday(county: str, week: date) -> bool:
    """Is the Monday-start `week` a school holiday week in this county?"""
    index = _county_index(county)
    mid = week + timedelta(days=3)
    year = mid.year
    shift = timedelta(days=(-7, 0, 7)[index % 3])
    end = week + timedelta(days=6)
    summer = date(year, 6, 14) + shift <= mid <= date(year, 8, 18) + shift
    winter = mid >= date(year, 12, 21) or mid <= date(year, 1, 3)
    spring_day = date(year, 3, 25) + timedelta(days=3 * index)
    spring = week <= spring_day <= end
    return summer or winter or spring or week <= thanksgiving(year) <= end


def benefit_week(county: str, week: date) -> bool:
    """Does the Monday-start `week` contain this county's benefit-issue day?"""
    _county_index(county)
    return any((week + timedelta(days=d)).day == BENEFIT_DAY[county] for d in range(7))
