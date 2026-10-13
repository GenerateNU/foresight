from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from foresight.repository import weather as weather_repo

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class WeatherCoverage:
    city: str
    start: date
    end: date
    days: int  # days in the window
    rows: int  # days with a row saved
    earliest: date | None  # first day with values
    missing: list[tuple[date, date]]  # no row at all
    empty: list[tuple[date, date]]  # row saved, values missing (archive lag)


async def weather_coverage(
    session: AsyncSession, *, city: str, start: date, end: date
) -> WeatherCoverage:
    """Count saved days and group the gaps into runs of consecutive days."""
    saved = await weather_repo.recorded_days(session, city=city, start=start, end=end)
    window = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    usable = [d for d, has_values in saved.items() if has_values]
    return WeatherCoverage(
        city=city,
        start=start,
        end=end,
        days=len(window),
        rows=len(saved),
        earliest=min(usable, default=None),
        missing=_spans(d for d in window if d not in saved),
        empty=_spans(sorted(d for d, has_values in saved.items() if not has_values)),
    )


def _spans(days: Iterable[date]) -> list[tuple[date, date]]:
    """Group sorted days into (first, last) runs of consecutive days."""
    spans: list[tuple[date, date]] = []
    for day in days:
        if spans and day == spans[-1][1] + timedelta(days=1):
            spans[-1] = (spans[-1][0], day)
        else:
            spans.append((day, day))
    return spans
