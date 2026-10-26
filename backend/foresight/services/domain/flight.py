"""Flights: daily arrival counts at a city's airport, per source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository.signals import flight as flight_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.signals.flight import FlightArrival


async def list_flight_arrivals(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[FlightArrival], int]:
    """Arrivals at the hotel's city airport. Each source keeps its own row per day."""
    hotel = await get_hotel(session, hotel_id)
    return await flight_repo.list_flight_arrivals(
        session, city_id=hotel.city_id, start=start, end=end, limit=limit, offset=offset
    )
