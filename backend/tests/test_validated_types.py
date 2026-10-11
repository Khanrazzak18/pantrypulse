"""The shared validated types every API boundary uses: ids, dates, months and text."""

from datetime import date

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.types import MAX_ID, BlockText, LineText, PositiveId, SafeDate, check_month


class Model(BaseModel):
    id: PositiveId
    day: SafeDate
    line: LineText
    block: BlockText


def make(**over):
    return Model(**{"id": 1, "day": date(2026, 1, 5), "line": "ok", "block": "ok", **over})


def test_a_normal_value_passes():
    assert make().id == 1


@pytest.mark.parametrize("bad", [0, -1, MAX_ID + 1, 99999999999999999999])
def test_ids_must_fit_the_database(bad):
    with pytest.raises(ValidationError):
        make(id=bad)


def test_the_largest_id_is_accepted():
    assert make(id=MAX_ID).id == MAX_ID


@pytest.mark.parametrize(
    "bad", [date(2019, 12, 31), date(2101, 1, 1), date(1, 1, 1), date(9999, 12, 31)]
)
def test_dates_must_be_between_2020_and_2100(bad):
    with pytest.raises(ValidationError, match="between 2020 and 2100"):
        make(day=bad)


@pytest.mark.parametrize("good", [date(2020, 1, 1), date(2100, 12, 31)])
def test_the_edges_of_the_date_range_are_accepted(good):
    assert make(day=good).day == good


@pytest.mark.parametrize("bad", ["a\u0000b", "a\u0007b", "a\u001fb", "a\u007fb", "a\u0085b"])
def test_control_characters_are_rejected_everywhere(bad):
    for field in ("line", "block"):
        with pytest.raises(ValidationError, match="control characters"):
            make(**{field: bad})


def test_one_line_text_rejects_newlines_and_tabs_but_block_text_allows_them():
    for bad in ("a\nb", "a\tb", "a\rb"):
        with pytest.raises(ValidationError):
            make(line=bad)
    assert make(block="a\nb\tc").block == "a\nb\tc"


def test_emoji_and_non_latin_text_are_fine():
    text = "🥕 مرحبا 你好 Привет"
    assert make(line=text, block=text).line == text


@pytest.mark.parametrize("good", ["2020-01", "2026-09", "2100-12"])
def test_months_in_range_pass(good):
    assert check_month(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "0000-01",
        "2019-12",
        "2101-01",
        "9999-12",
        "2026-13",
        "2026-00",
        "September",
        "2026-09-01",
        "",
    ],
)
def test_months_out_of_range_or_malformed_are_rejected(bad):
    with pytest.raises(ValueError, match="2020-01 and 2100-12"):
        check_month(bad)
