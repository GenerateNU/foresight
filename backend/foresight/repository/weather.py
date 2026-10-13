from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

from foresight.database.models.external import Weather
from foresight.repository import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import date

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("city", "weather_date", "is_forecast", "source")
_MEASURES = ("temp_max_c", "temp_min_c", "precip_mm", "wind_kph", "condition")


async def upsert_weather(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (city, weather_date, is_forecast, source)."""
    return await upsert_rows(
        session,
        cast("Table", Weather.__table__),
        constraint="uq_weather_city_date_kind_source",
        key=_KEY,
        mutable=_MEASURES,
        rows=rows,
    )


async def recorded_days(
    session: AsyncSession, *, city: str, start: date, end: date
) -> dict[date, bool]:
    """Days with recorded weather saved, mapped to whether it has a temperature."""
    result = await session.execute(
        select(Weather.weather_date, Weather.temp_max_c.is_not(None)).where(
            Weather.city == city,
            Weather.is_forecast.is_(False),
            Weather.weather_date.between(start, end),
        )
    )
    return {day: has_values for day, has_values in result.tuples().all()}
