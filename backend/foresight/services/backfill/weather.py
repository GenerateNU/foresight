"""Recorded and forecast weather for a hotel, fetched and saved."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import weather as weather_repo
from foresight.services.errors import DomainError
from foresight.services.ingest import open_meteo

if TYPE_CHECKING:
    from datetime import date

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.repository.upsert import Outcome


class MissingLocationError(DomainError):
    """The hotel has no coordinates, so there is nowhere to ask about."""


def _coords(hotel: Hotel) -> tuple[float, float]:
    if hotel.latitude is None or hotel.longitude is None:
        raise MissingLocationError(f"hotel {hotel.id} ({hotel.name}) has no lat/lon")
    return hotel.latitude, hotel.longitude


async def backfill_weather(
    session: AsyncSession,
    hotel: Hotel,
    *,
    start: date,
    end: date,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[Outcome, int]:
    """Fetch recorded weather for every day from `start` to `end` and save it.

    The archive stops at today. Does not commit; the caller owns the transaction.
    """
    latitude, longitude = _coords(hotel)
    async with open_meteo.client(transport=transport) as http:
        rows = await open_meteo.fetch_actuals(
            http,
            city=hotel.city,
            latitude=latitude,
            longitude=longitude,
            start=start,
            end=end,
            timezone=hotel.timezone or "auto",
        )
    return await weather_repo.upsert_weather(session, rows)


async def sync_forecast(
    session: AsyncSession,
    hotel: Hotel,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[Outcome, int]:
    """Fetch the next 16 days of forecast for the hotel and save it."""
    latitude, longitude = _coords(hotel)
    async with open_meteo.client(transport=transport) as http:
        rows = await open_meteo.fetch_forecast(
            http,
            city=hotel.city,
            latitude=latitude,
            longitude=longitude,
            timezone=hotel.timezone or "auto",
        )
    return await weather_repo.upsert_weather(session, rows)
