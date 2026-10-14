from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.database.models.signals.flight import FlightArrival
from foresight.repository.signals.flight import upsert_flight_arrivals
from foresight.repository.upsert import Outcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

AIRPORT = "TST"


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "airport": AIRPORT,
        "arrival_date": date(2026, 6, 1),
        "flight_count": 131,
        "avg_fare_eur": None,
        "source": "aerodatabox",
    } | overrides


async def _rows(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(FlightArrival)
        .where(FlightArrival.airport == AIRPORT)
    )


async def test_first_write_is_new(session: AsyncSession) -> None:
    counts = await upsert_flight_arrivals(session, [_row()])
    assert counts[Outcome.NEW] == 1
    assert await _rows(session) == 1


async def test_identical_rerun_adds_no_rows(session: AsyncSession) -> None:
    await upsert_flight_arrivals(session, [_row()])
    counts = await upsert_flight_arrivals(session, [_row()])
    assert counts == {Outcome.NEW: 0, Outcome.UPDATED: 0, Outcome.UNCHANGED: 1}
    assert await _rows(session) == 1


async def test_revised_count_updates_in_place(session: AsyncSession) -> None:
    await upsert_flight_arrivals(session, [_row()])
    counts = await upsert_flight_arrivals(session, [_row(flight_count=140)])
    assert counts[Outcome.UPDATED] == 1
    assert await _rows(session) == 1


async def test_each_source_keeps_its_own_row(session: AsyncSession) -> None:
    await upsert_flight_arrivals(
        session,
        [
            _row(source="cso", flight_count=100),
            _row(source="opensky", flight_count=120),
            _row(),
        ],
    )
    assert await _rows(session) == 3
