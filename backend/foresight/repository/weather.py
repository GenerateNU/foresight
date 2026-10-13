"""Data access for `weather`: daily forecasts and recorded actuals per city."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.database.models.weather import Weather
from foresight.repository.pagination import fetch_page
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("city", "weather_date", "is_forecast", "source")
_MEASURES = ("temp_max_c", "temp_min_c", "precip_mm", "wind_kph", "condition")


async def upsert_weather(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (city, weather_date, is_forecast, source)."""
    return await upsert_rows(
        session,
        Weather,
        constraint="uq_weather_city_weather_date_is_forecast_source",
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


async def list_weather(
    session: AsyncSession,
    *,
    city: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Weather], int]:
    # `weather.city` is free text, so compare without regard to case.
    stmt = select(Weather).where(func.lower(Weather.city) == city.lower())
    if start is not None:
        stmt = stmt.where(Weather.weather_date >= start)
    if end is not None:
        stmt = stmt.where(Weather.weather_date <= end)
    stmt = stmt.order_by(Weather.weather_date, Weather.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)
