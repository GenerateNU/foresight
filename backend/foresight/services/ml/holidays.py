from datetime import date, timedelta

import holidays
import numpy as np
import pandas as pd

_COUNTRY = "IE"


def days_off(years: range) -> set[date]:
    """Lists Ireland's public holidays, plus a weekday off for weekend ones.

    The library keeps a weekend holiday on its own date, as Irish law does,
    but most people get the next weekday off, and that moves demand: St
    Patrick's Day on Sunday 17 March 2024 gave Monday 18 March off. The day
    off is the next weekday that isn't already a holiday, so Christmas on a
    Sunday, with St Stephen's Day on Monday, gives Tuesday 27 December. Every
    hotel gets Ireland's holidays for now.

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

    Args:
        stay_date (pd.Series): Night dates, as datetimes.

    Returns:
        np.ndarray: 1 where the night is a day off, else 0, one per night.
    """
    return _is_day_off(stay_date)


def night_before_holiday(stay_date: pd.Series) -> np.ndarray:
    """Flags the nights whose next day is a day off for a public holiday.

    For example the Sunday before a Monday bank holiday, 24 December and 31
    December. A night that is itself a holiday counts only if the next day is
    one too, like 25 December.

    Args:
        stay_date (pd.Series): Night dates, as datetimes.

    Returns:
        np.ndarray: 1 where the next day is a day off, else 0, one per night.
    """
    return _is_day_off(stay_date + pd.Timedelta(days=1))


def _is_day_off(days: pd.Series) -> np.ndarray:
    """Flags the days that are a public holiday or its weekday off.

    The year before the first is included too, so a late-December holiday can
    carry its weekday off into January.

    Args:
        days (pd.Series): Dates, as datetimes.

    Returns:
        np.ndarray: 1 where the day is off, else 0, one per day.
    """
    if days.empty:
        return np.zeros(0, dtype=int)
    years = range(days.dt.year.min() - 1, days.dt.year.max() + 1)
    off = pd.to_datetime(sorted(days_off(years)))
    return days.isin(off).to_numpy().astype(int)
