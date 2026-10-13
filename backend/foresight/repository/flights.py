from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from foresight.database.models.external import FlightArrival
from foresight.repository import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("airport", "arrival_date", "source")
_MEASURES = ("flight_count", "avg_fare_eur")


async def upsert_flight_arrivals(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (airport, arrival_date, source).

    Each source keeps its own row; which one wins is a read-side decision.
    """
    return await upsert_rows(
        session,
        cast("Table", FlightArrival.__table__),
        constraint="uq_flight_arrivals_airport_date_source",
        key=_KEY,
        mutable=_MEASURES,
        rows=rows,
    )
