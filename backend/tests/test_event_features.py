"""Stored events turned into the per-night expected_attendance feature."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pytest
from generate_mock_data import generate
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from foresight.config import settings
from foresight.database.models.external import Event
from foresight.ingest.normalize import (
    DatePrecision,
    EventStatus,
    NormalizedEvent,
    Source,
)
from foresight.ingest.repository import upsert_event
from foresight.services.features.events import event_features, nightly_attendance

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

START, END = date(2026, 11, 13), date(2026, 11, 16)
DUBLIN = (53.3498, -6.2603)


def _event(**overrides: object) -> Event:
    base: dict[str, object] = {
        "start_local_date": date(2026, 11, 14),
        "end_local_date": date(2026, 11, 14),
        "expected_attendance": 12_000,
        "confidence": 1.0,
        "status": EventStatus.ACTIVE,
        "date_precision": DatePrecision.DAY,
        "latitude": None,
        "longitude": None,
    }
    return Event(**(base | overrides))


def _by_night(series) -> dict[date, int]:
    return {night: int(n) for night, n in series.items()}


def test_one_row_per_night_with_zero_on_quiet_nights():
    series = nightly_attendance([_event()], START, END)
    assert _by_night(series) == {
        date(2026, 11, 13): 0,
        date(2026, 11, 14): 12_000,
        date(2026, 11, 15): 0,
        date(2026, 11, 16): 0,
    }
    assert series.name == "expected_attendance"


def test_same_night_events_add_up():
    series = nightly_attendance(
        [_event(), _event(expected_attendance=3_000)], START, END
    )
    assert series[date(2026, 11, 14)] == 15_000


def test_multi_day_event_is_spread_over_its_nights():
    fair = _event(
        start_local_date=date(2026, 11, 14),
        end_local_date=date(2026, 11, 17),  # runs past the window
        expected_attendance=20_000,
    )
    series = nightly_attendance([fair], START, END)
    assert list(series) == [0, 5_000, 5_000, 5_000]


@pytest.mark.parametrize("status", [EventStatus.DELETED, EventStatus.CANCELLED])
def test_withdrawn_events_are_ignored(status):
    series = nightly_attendance([_event(status=status)], START, END)
    assert series.sum() == 0


def test_provisional_events_count_by_confidence():
    guess = _event(status=EventStatus.PROVISIONAL, confidence=0.25)
    assert nightly_attendance([guess], START, END)[date(2026, 11, 14)] == 3_000


def test_unusable_events_contribute_nothing():
    events = [
        _event(expected_attendance=None),
        _event(date_precision=DatePrecision.MONTH),
    ]
    assert nightly_attendance(events, START, END).sum() == 0


def test_radius_drops_far_venues_but_keeps_unlocated_ones():
    near = _event(latitude=53.344, longitude=-6.267)  # ~1 km from centre
    far = _event(latitude=53.427, longitude=-6.244, expected_attendance=500)  # ~9km
    unlocated = _event(expected_attendance=100)
    series = nightly_attendance(
        [near, far, unlocated],
        START,
        END,
        latitude=DUBLIN[0],
        longitude=DUBLIN[1],
        radius_km=5,
    )
    assert series[date(2026, 11, 14)] == 12_100


def test_generate_takes_attendance_without_changing_its_noise():
    days = 5
    attendance = np.array([0, 0, 30_000, 0, 0])
    quiet = generate(start="2026-11-13", days=days, expected_attendance=np.zeros(days))
    busy = generate(start="2026-11-13", days=days, expected_attendance=attendance)

    assert busy.groupby("stay_date")["expected_attendance"].first().tolist() == list(
        attendance
    )
    # Only the event night's derived features move.
    changed = (
        (busy["flight_count"] != quiet["flight_count"]).groupby(busy["stay_date"]).any()
    )
    assert changed.tolist() == [False, False, True, False, False]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(settings.database_url)
    try:
        conn = await engine.connect()
    except (OSError, ConnectionError) as exc:
        await engine.dispose()
        pytest.skip(f"Postgres unavailable: {exc}")

    trans = await conn.begin()
    async with AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint"
    ) as session:
        yield session
    await trans.rollback()
    await conn.close()
    await engine.dispose()


async def test_reads_the_market_from_the_events_table(session):
    for ref, city, attendance in [
        ("phq-features-1", "Testville", 4_000),
        ("phq-features-2", "Testville, Nowhere", 1_000),  # same market slug
        ("phq-features-3", "Elsewhere", 9_999),
    ]:
        await upsert_event(
            session,
            NormalizedEvent(
                source=Source.PREDICTHQ,
                source_ref=ref,
                title=f"Show {city} {attendance}",
                city=city,
                start_local_date=date(2026, 11, 14),
                end_local_date=date(2026, 11, 14),
                expected_attendance=attendance,
            ),
        )
    await session.flush()

    series = await event_features(session, city="Testville", start=START, end=END)
    assert series[date(2026, 11, 14)] == 5_000
    assert series.sum() == 5_000
