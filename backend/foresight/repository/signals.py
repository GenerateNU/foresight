"""Read-only data access for the external signals: weather, events, flights."""

from collections.abc import Collection, Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.external import Event, FlightArrival, Weather
from foresight.ingest.normalize import EventStatus
from foresight.repository.pagination import fetch_page


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


async def list_events(
    session: AsyncSession,
    *,
    city_slug: str,
    start: date | None,
    end: date | None,
    exclude_statuses: Collection[EventStatus],
    limit: int,
    offset: int,
) -> tuple[Sequence[Event], int]:
    """Events whose inclusive local-date range overlaps [start, end]."""
    stmt = select(Event).where(Event.city_slug == city_slug)
    if exclude_statuses:
        stmt = stmt.where(Event.status.not_in(exclude_statuses))
    if start is not None:
        stmt = stmt.where(Event.end_local_date >= start)
    if end is not None:
        stmt = stmt.where(Event.start_local_date <= end)
    stmt = stmt.order_by(Event.start_local_date, Event.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def list_flight_arrivals(
    session: AsyncSession,
    *,
    airport: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[FlightArrival], int]:
    stmt = select(FlightArrival).where(FlightArrival.airport == airport)
    if start is not None:
        stmt = stmt.where(FlightArrival.arrival_date >= start)
    if end is not None:
        stmt = stmt.where(FlightArrival.arrival_date <= end)
    stmt = stmt.order_by(FlightArrival.arrival_date, FlightArrival.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)
