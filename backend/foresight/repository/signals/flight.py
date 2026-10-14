"""Data access for `flight_arrivals`: arrivals per city per day, per source."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from foresight.database.models.signals.flight import FlightArrival
from foresight.repository.pagination import fetch_page
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("city_id", "arrival_date", "source")
_MEASURES = ("airport", "flight_count", "avg_fare_eur")


async def upsert_flight_arrivals(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (city_id, arrival_date, source).

    Each source keeps its own row; which one wins is a read-side decision.
    """
    return await upsert_rows(
        session,
        FlightArrival,
        constraint="uq_flight_arrivals_city_id_arrival_date_source",
        key=_KEY,
        mutable=_MEASURES,
        rows=rows,
    )


async def list_flight_arrivals(
    session: AsyncSession,
    *,
    city_id: int,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[FlightArrival], int]:
    stmt = select(FlightArrival).where(FlightArrival.city_id == city_id)
    if start is not None:
        stmt = stmt.where(FlightArrival.arrival_date >= start)
    if end is not None:
        stmt = stmt.where(FlightArrival.arrival_date <= end)
    stmt = stmt.order_by(
        FlightArrival.arrival_date, FlightArrival.source, FlightArrival.id
    )
    return await fetch_page(session, stmt, limit=limit, offset=offset)
