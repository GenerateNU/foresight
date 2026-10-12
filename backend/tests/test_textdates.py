"""Date resolution: the formats announcements actually use, and what we refuse."""

from __future__ import annotations

from datetime import date

import pytest

from foresight.ingest.normalize import DatePrecision
from foresight.ingest.textdates import looks_retrospective, resolve_date

REFERENCE = date(2026, 6, 1)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("runs on August 28, 2026", date(2026, 8, 28), date(2026, 8, 28)),
        ("runs 28 August 2026", date(2026, 8, 28), date(2026, 8, 28)),
        ("August 28-30, 2026", date(2026, 8, 28), date(2026, 8, 30)),
        ("28-30 August 2026", date(2026, 8, 28), date(2026, 8, 30)),
        ("Aug. 28th to 30th, 2026", date(2026, 8, 28), date(2026, 8, 30)),
        ("on 2026-08-28", date(2026, 8, 28), date(2026, 8, 28)),
        ("2026-08-28 to 2026-08-30", date(2026, 8, 28), date(2026, 8, 30)),
        # Ranges that roll into the next month, and the next year.
        ("August 30 - September 2, 2026", date(2026, 8, 30), date(2026, 9, 2)),
        ("December 30 - January 2, 2026", date(2026, 12, 30), date(2027, 1, 2)),
        # A year stated on both sides of the dash.
        (
            "December 30, 2026 - January 1, 2027",
            date(2026, 12, 30),
            date(2027, 1, 1),
        ),
        # A range written as prose rather than punctuation.
        (
            "opens December 1, 2026 and runs through January 4, 2027",
            date(2026, 12, 1),
            date(2027, 1, 4),
        ),
        ("runs July 1 through July 9, 2027", date(2027, 7, 1), date(2027, 7, 9)),
    ],
)
def test_day_precision_formats(text: str, start: date, end: date) -> None:
    resolved = resolve_date(text, REFERENCE)

    assert resolved is not None
    assert (resolved.start, resolved.end) == (start, end)
    assert resolved.precision is DatePrecision.DAY


def test_missing_year_is_inferred_forward() -> None:
    resolved = resolve_date("the festival returns August 28", REFERENCE)

    assert resolved is not None
    assert resolved.start == date(2026, 8, 28)
    assert not resolved.had_explicit_year


def test_missing_year_rolls_over_when_the_month_has_passed() -> None:
    """In June, an undated "March 14" means next March."""
    resolved = resolve_date("tickets for March 14", REFERENCE)

    assert resolved is not None
    assert resolved.start == date(2027, 3, 14)


def test_month_year_keeps_month_precision() -> None:
    resolved = resolve_date("sometime in August 2026", REFERENCE)

    assert resolved is not None
    assert resolved.precision is DatePrecision.MONTH
    assert (resolved.start, resolved.end) == (date(2026, 8, 1), date(2026, 8, 31))


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("summer 2026", date(2026, 6, 1), date(2026, 8, 31)),
        ("autumn 2026", date(2026, 9, 1), date(2026, 11, 30)),
        ("winter 2026", date(2026, 12, 1), date(2027, 2, 28)),
        ("Q3 2026", date(2026, 7, 1), date(2026, 9, 30)),
    ],
)
def test_coarse_spans_keep_quarter_precision(text: str, start: date, end: date) -> None:
    resolved = resolve_date(text, REFERENCE)

    assert resolved is not None
    assert resolved.precision is DatePrecision.QUARTER
    assert (resolved.start, resolved.end) == (start, end)


def test_finest_precision_wins_when_a_text_carries_several() -> None:
    text = "announced for summer 2026, with the main stage on August 28, 2026"

    resolved = resolve_date(text, REFERENCE)

    assert resolved is not None
    assert resolved.precision is DatePrecision.DAY
    assert resolved.start == date(2026, 8, 28)


def test_impossible_calendar_date_is_skipped_for_the_next_candidate() -> None:
    resolved = resolve_date("February 30, 2026 -- sorry, July 3, 2026", REFERENCE)

    assert resolved is not None
    assert resolved.start == date(2026, 7, 3)


@pytest.mark.parametrize(
    "text",
    [
        "happening this weekend",
        "next Friday at the venue",
        "coming soon to the city",
        "no date has been announced",
    ],
)
def test_relative_and_absent_dates_are_refused(text: str) -> None:
    assert resolve_date(text, REFERENCE) is None


def test_date_already_past_relative_to_the_reference_is_refused() -> None:
    assert resolve_date("was on January 5, 2020", REFERENCE) is None


def test_retrospective_coverage_is_flagged() -> None:
    assert looks_retrospective("the festival took place over the weekend")


def test_a_forward_looking_marker_rescues_a_retrospective_recap() -> None:
    text = "last year's festival drew crowds; this year's runs August 28-30, 2026"

    assert not looks_retrospective(text)
