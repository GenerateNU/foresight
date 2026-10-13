from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import pytest
from sqlalchemy import select

from foresight.database.models.external import FlightArrival
from foresight.services.backfill.flights import (
    FlightBackfillStoppedError,
    backfill_flights,
)
from foresight.services.flight_data_service import RateLimitedError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

AIRPORT = "TST"


async def _saved(session: AsyncSession) -> dict[date, int | None]:
    rows = await session.scalars(
        select(FlightArrival).where(FlightArrival.airport == AIRPORT)
    )
    return {row.arrival_date: row.flight_count for row in rows}


async def test_rate_limit_keeps_earlier_days_and_rerun_overwrites(
    session: AsyncSession,
) -> None:
    def rate_limited_on_june_2(start: date, end: date, airport: str) -> pd.DataFrame:
        if start == date(2026, 6, 2):
            raise RateLimitedError("Too many requests")
        return pd.DataFrame({"flight_number": ["EI 1", "EI 2"]})

    saved_days = []
    with pytest.raises(FlightBackfillStoppedError) as stopped:
        async for day, _ in backfill_flights(
            session,
            date(2026, 6, 1),
            date(2026, 6, 3),
            AIRPORT,
            fetch=rate_limited_on_june_2,
        ):
            saved_days.append(day)
    assert stopped.value.day == date(2026, 6, 2)
    assert saved_days == [date(2026, 6, 1)]
    assert await _saved(session) == {date(2026, 6, 1): 2}

    def one_flight(start: date, end: date, airport: str) -> pd.DataFrame:
        return pd.DataFrame({"flight_number": ["EI 1"]})

    async for _ in backfill_flights(
        session, date(2026, 6, 1), date(2026, 6, 3), AIRPORT, fetch=one_flight
    ):
        pass
    assert await _saved(session) == {
        date(2026, 6, 1): 1,
        date(2026, 6, 2): 1,
        date(2026, 6, 3): 1,
    }
