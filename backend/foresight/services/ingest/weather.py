"""Recorded and forecast weather for a city, fetched and saved."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository.signals import weather as weather_repo
from foresight.services.adapters import open_meteo

if TYPE_CHECKING:
    from datetime import date

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City
    from foresight.repository.upsert import Outcome


async def ingest_actuals(
    session: AsyncSession,
    city: City,
    *,
    start: date,
    end: date,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[Outcome, int]:
    """Fetch recorded weather for every day from `start` to `end` and save it.

    The archive stops at today. Does not commit; the caller owns the transaction.
    """
    async with open_meteo.client(transport=transport) as http:
        rows = await open_meteo.fetch_actuals(
            http,
            latitude=city.latitude,
            longitude=city.longitude,
            start=start,
            end=end,
            timezone=city.timezone,
        )
    return await weather_repo.upsert_weather(session, _for(city, rows))


async def ingest_forecast(
    session: AsyncSession,
    city: City,
    *,
    start: date | None = None,
    end: date | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[Outcome, int]:
    """Fetch the next 16 days of forecast and save the days in `start`..`end`
    (all of them when omitted)."""
    async with open_meteo.client(transport=transport) as http:
        rows = await open_meteo.fetch_forecast(
            http,
            latitude=city.latitude,
            longitude=city.longitude,
            timezone=city.timezone,
        )
    rows = [
        row
        for row in rows
        if (start is None or row["weather_date"] >= start)
        and (end is None or row["weather_date"] <= end)
    ]
    return await weather_repo.upsert_weather(session, _for(city, rows))


def _for(city: City, rows: list[dict]) -> list[dict]:
    return [{**row, "city_id": city.id} for row in rows]
