"""How completely recorded weather covers a date window."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from foresight.repository import hotel as hotel_repo
from foresight.repository.signals import weather as weather_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.ingest.window import InvalidWindowError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class DateSpan:
    """Consecutive days, both ends inclusive."""

    first: date
    last: date


@dataclass(frozen=True, slots=True)
class WeatherCoverage:
    city_id: int
    start: date
    end: date
    days: int  # days in the window
    rows: int  # days with a row saved
    earliest: date | None  # first day with values
    missing: list[DateSpan]  # no row at all
    empty: list[DateSpan]  # row saved, values missing (archive lag)


async def weather_coverage(
    session: AsyncSession, *, city_id: int, start: date, end: date
) -> WeatherCoverage:
    """Count saved days and group the gaps into runs of consecutive days."""
    saved = await weather_repo.recorded_days(
        session, city_id=city_id, start=start, end=end
    )
    window = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    usable = [d for d, has_values in saved.items() if has_values]
    return WeatherCoverage(
        city_id=city_id,
        start=start,
        end=end,
        days=len(window),
        rows=len(saved),
        earliest=min(usable, default=None),
        missing=_spans(d for d in window if d not in saved),
        empty=_spans(sorted(d for d, has_values in saved.items() if not has_values)),
    )


async def hotel_weather_coverage(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> WeatherCoverage:
    """Coverage of the hotel's city; omitted dates default to its loaded nights."""
    hotel = await get_hotel(session, hotel_id)
    if start is None or end is None:
        loaded = await hotel_repo.stay_date_range(session, hotel.id)
        if loaded is None:
            raise InvalidWindowError(
                "no hotel nights loaded; load performance data or give both "
                "start and end"
            )
        start, end = start or loaded[0], end or loaded[1]
    if start > end:
        raise InvalidWindowError(f"start {start} is after end {end}")
    return await weather_coverage(session, city_id=hotel.city_id, start=start, end=end)


def _spans(days: Iterable[date]) -> list[DateSpan]:
    """Group sorted days into runs of consecutive days."""
    spans: list[DateSpan] = []
    for day in days:
        if spans and day == spans[-1].last + timedelta(days=1):
            spans[-1] = DateSpan(spans[-1].first, day)
        else:
            spans.append(DateSpan(day, day))
    return spans
