"""Public holidays, from the `holidays` library rather than ingested data.

For inputs known from the date alone: a night's value never depends on what has
been ingested, so it is the same when training on the past and when pricing a
night 90 days out (decision 0067). Every holiday input comes from here; none
from PredictHQ (decision 0083). School holidays aren't in the library, so the
model doesn't read them.
"""

from datetime import date, timedelta

import holidays
import numpy as np
import pandas as pd

# Ireland only for now. A hotel elsewhere gets Ireland's holidays (0067).
_COUNTRY = "IE"


def days_off(years: range) -> set[date]:
    """Every public holiday in `years`, plus the weekday off for each one that
    falls on a weekend.

    The library keeps a weekend holiday on its own date, as Irish law does, but
    most people get the next weekday off (banks close), and that is what moves
    demand: St Patrick's Day on Sunday 17 March 2024 gave Monday 18 March off.
    The day off is the next weekday that isn't already a holiday, so Christmas
    on a Sunday, with St Stephen's Day on Monday, gives Tuesday 27 December.

    Args:
        years (range): The calendar years to cover.

    Returns:
        set[date]: The holidays and their weekdays off.
    """
    official = set(holidays.country_holidays(_COUNTRY, years=years))
    off = set(official)
    for day in sorted(official):
        if day.weekday() < 5:
            continue
        sub = day + timedelta(days=1)
        while sub.weekday() >= 5 or sub in off:
            sub += timedelta(days=1)
        off.add(sub)
    return off


def public_holiday(stay_date: pd.Series) -> np.ndarray:
    """Flags the nights that are themselves a day off for a public holiday.

    The same days as `night_before_holiday` looks ahead to, so the two flags
    always agree on what a holiday is (decision 0083).

    Args:
        stay_date (pd.Series): Night dates, as datetimes.

    Returns:
        np.ndarray: 1 where the night is a day off, else 0, one per night.
    """
    return _is_day_off(stay_date)


def night_before_holiday(stay_date: pd.Series) -> np.ndarray:
    """Flags the nights whose next day is a day off for a public holiday.

    E.g. the Sunday before a Monday bank holiday, 24 December, 31 December. A
    night that is itself a holiday counts only if the next day is one too
    (25 December).

    Args:
        stay_date (pd.Series): Night dates, as datetimes.

    Returns:
        np.ndarray: 1 where the next day is a day off, else 0, one per night.
    """
    return _is_day_off(stay_date + pd.Timedelta(days=1))


def _is_day_off(days: pd.Series) -> np.ndarray:
    """1 where the day is a public holiday or its weekday off, else 0."""
    if days.empty:
        return np.zeros(0, dtype=int)
    # One year early too, so a holiday in late December can carry its weekday
    # off into January.
    years = range(days.dt.year.min() - 1, days.dt.year.max() + 1)
    off = pd.to_datetime(sorted(days_off(years)))
    return days.isin(off).to_numpy().astype(int)
