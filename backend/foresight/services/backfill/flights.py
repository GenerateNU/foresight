from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from foresight.repository.flights import upsert_flight_arrivals
from foresight.services.flight_data_service import RateLimitedError, fetch_aerodatabox

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from datetime import date

    import pandas as pd
    from sqlalchemy.ext.asyncio import AsyncSession

SOURCE = "aerodatabox"


class FlightBackfillStoppedError(Exception):
    """AeroDataBox rate limited us; `day` is the first day not saved."""

    def __init__(self, day: date, reason: str) -> None:
        super().__init__(f"rate limited on {day}: {reason}")
        self.day = day


async def backfill_flights(
    session: AsyncSession,
    start: date,
    end: date,
    airport: str = "DUB",
    fetch: Callable[[date, date, str], pd.DataFrame] = fetch_aerodatabox,
) -> AsyncIterator[tuple[date, int]]:
    """Fetch and save the arrival count for each day from `start` to `end`.

    Yields (day, count) after each day is written, so the caller can commit
    day by day. Does not commit itself.

    Raises:
        FlightBackfillStoppedError: If AeroDataBox rate limits us; every day yielded
            before it is complete.
    """
    day = start
    while day <= end:
        try:
            flights = fetch(day, day, airport)
        except RateLimitedError as exc:
            raise FlightBackfillStoppedError(day, str(exc)) from exc
        await upsert_flight_arrivals(
            session,
            [
                {
                    "airport": airport,
                    "arrival_date": day,
                    "flight_count": len(flights),
                    "avg_fare_eur": None,
                    "source": SOURCE,
                }
            ],
        )
        yield day, len(flights)
        day += timedelta(days=1)
