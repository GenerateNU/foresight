"""Business logic for reading the external signals (weather, events, flights)."""

from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.external import Event, FlightArrival, Weather
from foresight.ingest.normalize import EventStatus, slugify_city
from foresight.repository import signals as signals_repo

# Withdrawn or called-off events shouldn't count as demand.
_INACTIVE_EVENT_STATUSES = (EventStatus.DELETED, EventStatus.CANCELLED)


async def list_weather(
    session: AsyncSession,
    *,
    city: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Weather], int]:
    return await signals_repo.list_weather(
        session, city=city, start=start, end=end, limit=limit, offset=offset
    )


async def list_events(
    session: AsyncSession,
    *,
    city: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Event], int]:
    return await signals_repo.list_events(
        session,
        city_slug=slugify_city(city),
        start=start,
        end=end,
        exclude_statuses=_INACTIVE_EVENT_STATUSES,
        limit=limit,
        offset=offset,
    )


async def list_flight_arrivals(
    session: AsyncSession,
    *,
    airport: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[FlightArrival], int]:
    return await signals_repo.list_flight_arrivals(
        session, airport=airport, start=start, end=end, limit=limit, offset=offset
    )
