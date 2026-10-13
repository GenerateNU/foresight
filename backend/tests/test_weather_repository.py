from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.database.models.external import Weather
from foresight.repository import Outcome
from foresight.repository.weather import recorded_days, upsert_weather

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CITY = "Testville"


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "city": CITY,
        "weather_date": date(2026, 6, 1),
        "is_forecast": False,
        "source": "open-meteo",
        "temp_max_c": 18.0,
        "temp_min_c": 9.0,
        "precip_mm": 0.0,
        "wind_kph": 12.0,
        "condition": "cloudy",
    } | overrides


async def _rows(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count()).select_from(Weather).where(Weather.city == CITY)
    )


async def test_first_write_is_new(session: AsyncSession) -> None:
    counts = await upsert_weather(session, [_row()])
    assert counts[Outcome.NEW] == 1
    assert await _rows(session) == 1


async def test_identical_rerun_adds_no_rows(session: AsyncSession) -> None:
    await upsert_weather(session, [_row()])
    counts = await upsert_weather(session, [_row()])
    assert counts == {Outcome.NEW: 0, Outcome.UPDATED: 0, Outcome.UNCHANGED: 1}
    assert await _rows(session) == 1


async def test_revised_measure_updates_in_place(session: AsyncSession) -> None:
    await upsert_weather(session, [_row()])
    counts = await upsert_weather(session, [_row(temp_max_c=21.5)])
    assert counts[Outcome.UPDATED] == 1
    assert await _rows(session) == 1
    assert (
        await session.scalar(select(Weather.temp_max_c).where(Weather.city == CITY))
        == 21.5
    )


async def test_forecast_and_actual_are_separate_rows(session: AsyncSession) -> None:
    await upsert_weather(session, [_row(), _row(is_forecast=True)])
    assert await _rows(session) == 2


async def test_second_source_is_its_own_row(session: AsyncSession) -> None:
    await upsert_weather(session, [_row(), _row(source="other-provider")])
    assert await _rows(session) == 2


async def test_empty_batch_writes_nothing(session: AsyncSession) -> None:
    assert await upsert_weather(session, []) == dict.fromkeys(Outcome, 0)
    assert await _rows(session) == 0


async def test_an_update_restamps_captured_at(session: AsyncSession) -> None:
    # upsert_rows only stamps captured_at on tables that have the column, so
    # the tables that do must keep getting it.
    await upsert_weather(session, [_row()])
    first = await session.scalar(
        select(Weather.captured_at).where(Weather.city == CITY)
    )
    await upsert_weather(session, [_row(temp_max_c=21.0)])
    assert (
        await session.scalar(select(Weather.captured_at).where(Weather.city == CITY))
    ) > first


async def test_recorded_days_flags_days_without_values(session: AsyncSession) -> None:
    await upsert_weather(
        session,
        [
            _row(weather_date=date(2026, 6, 1)),
            _row(weather_date=date(2026, 6, 2), temp_max_c=None),
            _row(weather_date=date(2026, 6, 3), is_forecast=True),
        ],
    )
    days = await recorded_days(
        session, city=CITY, start=date(2026, 6, 1), end=date(2026, 6, 30)
    )
    assert days == {date(2026, 6, 1): True, date(2026, 6, 2): False}
