"""Resolve event dates out of prose.

Text sources announce dates the way people write them -- "August 28-30",
"next summer", "Q3 2026" -- while pricing needs a concrete local stay-night.
This module turns the former into the latter, or refuses, and always reports
how precisely it managed it.

Relative expressions ("this weekend", "next Friday") are deliberately not
resolved: they are only correct relative to a publication moment we do not
always trust, and a wrong date is worse here than a missing one.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from foresight.ingest.normalize import DatePrecision

MAX_LOOKAHEAD_DAYS = 540
_PAST_TOLERANCE_DAYS = 2

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# Northern-hemisphere seasons: start month, length in months.
_SEASONS = {
    "spring": (3, 3),
    "summer": (6, 3),
    "fall": (9, 3),
    "autumn": (9, 3),
    "winter": (12, 3),
}

# "opens December 1 and runs through January 4" is a range too, not two dates.
_RUN_PHRASE = r"(?:and\s+)?(?:will\s+)?runs?\s+(?:through|until|to)"
_DASH = rf"(?:{_RUN_PHRASE}|--|-|‐|‑|‒|–|—|through|until|thru|to)"
_ORD = r"(?:st|nd|rd|th)?"

_ISO = re.compile(
    rf"\b(\d{{4}})-(\d{{2}})-(\d{{2}})\b(?:\s*{_DASH}\s*(\d{{4}})-(\d{{2}})-(\d{{2}})\b)?"
)
# (?!\d) on every day group: without it "28 August 2026" reads the "20" of
# the year as the day and silently resolves eight days early.
_DAY = r"(\d{1,2})(?!\d)"
_YEAR = r"(\d{4})(?!\d)"

# A year can sit on either side of the dash: "December 30, 2026 - January 1, 2027".
_MONTH_DAY = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+{_DAY}{_ORD}(?:,?\s*{_YEAR})?"
    rf"(?:\s*{_DASH}\s*(?:({_MONTH_ALT})\.?\s+)?{_DAY}{_ORD}(?:,?\s*{_YEAR})?)?",
    re.I,
)
_DAY_MONTH = re.compile(
    rf"\b{_DAY}{_ORD}(?:\s*{_DASH}\s*{_DAY}{_ORD})?\s+(?:of\s+)?({_MONTH_ALT})\.?"
    rf"(?:,?\s*{_YEAR})?",
    re.I,
)
_MONTH_YEAR = re.compile(rf"\b({_MONTH_ALT})\.?,?\s+{_YEAR}", re.I)
_SEASON_YEAR = re.compile(rf"\b({'|'.join(_SEASONS)})\s+(?:of\s+)?(\d{{4}})\b", re.I)
_QUARTER_YEAR = re.compile(r"\bQ([1-4])\s*(?:of\s*)?(\d{4})\b", re.I)

_RETROSPECTIVE = re.compile(
    r"\b(?:was|were)\s+held\b|\btook\s+place\b|\bwrapped\s+up\b"
    r"|\bdrew\s+(?:a\s+)?crowds?\b|\bconcluded\b|\blast\s+year'?s?\b",
    re.I,
)
_FORWARD_LOOKING = re.compile(
    r"\bwill\b|\bannounc\w+\b|\bupcoming\b|\breturns?\b|\bset\s+for\b|\bscheduled\b"
    r"|\bgo\s+on\s+sale\b|\btickets?\b|\bthis\s+year'?s?\b|\bnext\s+year'?s?\b"
    r"|\bline-?up\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ResolvedDate:
    start: date
    end: date
    precision: DatePrecision
    had_explicit_year: bool


def looks_retrospective(text: str) -> bool:
    """True for articles reporting on an event that already happened.

    A forward-looking marker wins: write-ups routinely recap last year before
    announcing this year's dates, and those are the articles worth keeping.
    """
    return bool(_RETROSPECTIVE.search(text)) and not _FORWARD_LOOKING.search(text)


def _month_number(name: str) -> int:
    return _MONTHS[name.lower().rstrip(".")]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _end_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _infer_year(month: int, day: int, reference: date) -> int | None:
    """Pick the year that puts an undated "August 28" in the plausible future."""
    for year in (reference.year, reference.year + 1):
        candidate = _safe_date(year, month, day)
        if candidate and (candidate - reference).days >= -_PAST_TOLERANCE_DAYS:
            return year
    return None


def _span_from_months(start_month: int, months: int, year: int) -> tuple[date, date]:
    start = date(year, start_month, 1)
    end_month, end_year = start_month + months - 1, year
    if end_month > 12:
        end_month, end_year = end_month - 12, year + 1
    return start, _end_of_month(end_year, end_month)


def _day_range(
    month: int,
    day: int,
    end_month: int | None,
    end_day: int | None,
    year: int,
    end_year: int | None = None,
) -> tuple[date, date] | None:
    start = _safe_date(year, month, day)
    if not start:
        return None
    end = start
    if end_day:
        # "August 28 - September 1" and "December 30 - January 2" both roll
        # forward, the latter into the next year.
        target_month = end_month or month
        resolved = end_year or (year + 1 if target_month < month else year)
        parsed_end = _safe_date(resolved, target_month, end_day)
        if parsed_end and parsed_end >= start:
            end = parsed_end
    return start, end


def _try_iso(text: str, _reference: date) -> ResolvedDate | None:
    match = _ISO.search(text)
    if not match:
        return None
    start = _safe_date(int(match[1]), int(match[2]), int(match[3]))
    if not start:
        return None
    end = start
    if match[4]:
        parsed_end = _safe_date(int(match[4]), int(match[5]), int(match[6]))
        if parsed_end and parsed_end >= start:
            end = parsed_end
    return ResolvedDate(start, end, DatePrecision.DAY, had_explicit_year=True)


def _try_month_day(text: str, reference: date) -> ResolvedDate | None:
    for match in _MONTH_DAY.finditer(text):
        month, day = _month_number(match[1]), int(match[2])
        start_year = int(match[3]) if match[3] else None
        end_month = _month_number(match[4]) if match[4] else None
        end_day = int(match[5]) if match[5] else None
        end_year = int(match[6]) if match[6] else None

        # "December 30 - January 2, 2026" states one year for a span that
        # crosses New Year. It belongs to the start; the end rolls over.
        wraps = end_month is not None and end_month < month
        if start_year is not None:
            year, effective_end_year = start_year, end_year
        elif end_year is not None:
            year = end_year
            effective_end_year = end_year + 1 if wraps else end_year
        else:
            year, effective_end_year = _infer_year(month, day, reference), None
        if year is None:
            continue

        span = _day_range(month, day, end_month, end_day, year, effective_end_year)
        if span:
            explicit = start_year is not None or end_year is not None
            return ResolvedDate(*span, DatePrecision.DAY, explicit)
    return None


def _try_day_month(text: str, reference: date) -> ResolvedDate | None:
    for match in _DAY_MONTH.finditer(text):
        day = int(match[1])
        end_day = int(match[2]) if match[2] else None
        month = _month_number(match[3])
        explicit_year = int(match[4]) if match[4] else None
        year = explicit_year or _infer_year(month, day, reference)
        if year is None:
            continue
        span = _day_range(month, day, None, end_day, year)
        if span:
            return ResolvedDate(*span, DatePrecision.DAY, explicit_year is not None)
    return None


def _try_month_year(text: str, _reference: date) -> ResolvedDate | None:
    match = _MONTH_YEAR.search(text)
    if not match:
        return None
    start, end = _span_from_months(_month_number(match[1]), 1, int(match[2]))
    return ResolvedDate(start, end, DatePrecision.MONTH, had_explicit_year=True)


def _try_season_year(text: str, _reference: date) -> ResolvedDate | None:
    match = _SEASON_YEAR.search(text)
    if not match:
        return None
    start_month, months = _SEASONS[match[1].lower()]
    start, end = _span_from_months(start_month, months, int(match[2]))
    return ResolvedDate(start, end, DatePrecision.QUARTER, had_explicit_year=True)


def _try_quarter_year(text: str, _reference: date) -> ResolvedDate | None:
    match = _QUARTER_YEAR.search(text)
    if not match:
        return None
    start, end = _span_from_months(int(match[1]) * 3 - 2, 3, int(match[2]))
    return ResolvedDate(start, end, DatePrecision.QUARTER, had_explicit_year=True)


# Finest precision first: text carrying both "August 28, 2026" and "summer
# 2026" must resolve to the day, not the season.
_RESOLVERS = (
    _try_iso,
    _try_month_day,
    _try_day_month,
    _try_month_year,
    _try_season_year,
    _try_quarter_year,
)


def resolve_date(text: str, reference: date) -> ResolvedDate | None:
    """First date in `text` that could plausibly still be ahead of `reference`."""
    for resolver in _RESOLVERS:
        resolved = resolver(text, reference)
        if resolved and (resolved.end - reference).days >= -_PAST_TOLERANCE_DAYS:
            return resolved
    return None
