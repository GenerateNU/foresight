"""Data access for `weather`: daily forecasts and recorded actuals per city."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Integer, cast, extract, func, select

from foresight.database.models.signals.weather import Weather
from foresight.repository.pagination import fetch_page
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("city_id", "weather_date", "is_forecast", "source")
_MEASURES = ("temp_max_c", "temp_min_c", "precip_mm", "wind_kph", "condition")


async def upsert_weather(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (city_id, weather_date, is_forecast, source)."""
    return await upsert_rows(
        session,
        Weather,
        constraint="uq_weather_city_id_weather_date_is_forecast_source",
        key=_KEY,
        mutable=_MEASURES,
        rows=rows,
    )


async def recorded_days(
    session: AsyncSession, *, city_id: int, start: date, end: date
) -> dict[date, bool]:
    """Days with recorded weather saved, mapped to whether it has a temperature."""
    result = await session.execute(
        select(Weather.weather_date, Weather.temp_max_c.is_not(None)).where(
            Weather.city_id == city_id,
            Weather.is_forecast.is_(False),
            Weather.weather_date.between(start, end),
        )
    )
    return {day: has_values for day, has_values in result.tuples().all()}


async def list_weather(
    session: AsyncSession,
    *,
    city_id: int,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Weather], int]:
    stmt = select(Weather).where(Weather.city_id == city_id)
    if start is not None:
        stmt = stmt.where(Weather.weather_date >= start)
    if end is not None:
        stmt = stmt.where(Weather.weather_date <= end)
    stmt = stmt.order_by(Weather.weather_date, Weather.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def daily_weather(
    session: AsyncSession, *, city_id: int, start: date, end: date
) -> Sequence[Mapping[str, Any]]:
    """Recorded and forecast rows for the days in [start, end], every source.

    Rows carry weather_date, is_forecast, source, temp_max_c, precip_mm and
    wind_kph. The caller picks one row per day.
    """
    stmt = (
        select(
            Weather.weather_date,
            Weather.is_forecast,
            Weather.source,
            Weather.temp_max_c,
            Weather.precip_mm,
            Weather.wind_kph,
        )
        .where(Weather.city_id == city_id, Weather.weather_date.between(start, end))
        .order_by(Weather.weather_date, Weather.is_forecast, Weather.source)
    )
    return (await session.execute(stmt)).mappings().all()


async def typical_week(
    session: AsyncSession, *, city_id: int, iso_week: int
) -> Mapping[str, Any] | None:
    """Average recorded weather for one ISO week across every year saved.

    Returns years (how many distinct years contributed), temp_max_c, precip_mm
    and wind_kph, or None when nothing is recorded for that week.
    """
    week = cast(extract("week", Weather.weather_date), Integer)
    row = (
        (
            await session.execute(
                select(
                    func.count(
                        func.distinct(extract("isoyear", Weather.weather_date))
                    ).label("years"),
                    func.avg(Weather.temp_max_c).label("temp_max_c"),
                    func.avg(Weather.precip_mm).label("precip_mm"),
                    func.avg(Weather.wind_kph).label("wind_kph"),
                ).where(
                    Weather.city_id == city_id,
                    Weather.is_forecast.is_(False),
                    week == iso_week,
                )
            )
        )
        .mappings()
        .one()
    )
    return row if row["years"] else None
