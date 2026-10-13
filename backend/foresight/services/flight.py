"""Flights: daily arrival counts per airport, per source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import flight as flight_repo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.flight import FlightArrival


async def list_flight_arrivals(
    session: AsyncSession,
    *,
    airport: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[FlightArrival], int]:
    """Arrivals for an airport code exactly as stored (sources differ: DUB, EIDW)."""
    return await flight_repo.list_flight_arrivals(
        session, airport=airport, start=start, end=end, limit=limit, offset=offset
    )
