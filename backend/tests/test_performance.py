"""The Actual & Forecast import: blocks, rooms out of service and waitlist,
occupancy from sellable rooms, and older exports without those columns.

Parsing tests need no database. The saving test uses the rolled-back `session`.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from foresight.database.models import DailyPerformance, Hotel
from foresight.repository.upsert import Outcome
from foresight.routes.hotel import DailyPerformanceResponse
from foresight.services.adapters.hotel_csv import HotelDataParser
from foresight.services.ingest import performance

SAMPLE = (Path(__file__).parents[1] / "data" / "Actual & Forecast.csv").read_bytes()


def parse(content: bytes) -> list[dict]:
    parser = HotelDataParser(io.BytesIO(content))
    parser.run()
    return parser.rows(room_type_id=1)


def without_columns(*columns: str) -> bytes:
    """The sample file as an older export that didn't have these columns."""
    frame = pd.read_csv(io.BytesIO(SAMPLE), dtype=str)
    return frame.drop(columns=list(columns)).to_csv(index=False).encode()


def night(**changes) -> DailyPerformanceResponse:
    values = {
        "id": 1,
        "room_type_id": 1,
        "stay_date": date(2025, 9, 1),
        "rate": Decimal("150"),
        "rooms_available": 10,
        "rooms_sold": 9,
        "room_revenue": Decimal("1350"),
        "rooms_blocked": 0,
        "rooms_out_of_service": 1,
        "waitlist": 0,
    }
    return DailyPerformanceResponse(**{**values, **changes})


# Parsing


def test_sample_reads_every_night() -> None:
    rows = parse(SAMPLE)

    assert len(rows) == 14
    assert rows[0]["stay_date"] == date(2025, 9, 1)


def test_sample_reads_blocks_out_of_service_and_waitlist() -> None:
    first = parse(SAMPLE)[0]  # 1 Sep 2025: 9 sold, 1 out of service, 10 in stock

    assert first["rooms_out_of_service"] == 1
    assert first["rooms_blocked"] == 0
    assert first["waitlist"] == 0


def test_older_export_still_loads() -> None:
    rows = parse(without_columns("Blocks", "ROOS", "Waitlist"))

    assert len(rows) == 14
    assert rows[0]["rooms_out_of_service"] is None
    assert rows[0]["rooms_blocked"] is None
    assert rows[0]["waitlist"] is None


# Occupancy


def test_sold_out_night_with_a_room_out_of_service_is_full() -> None:
    assert night(rooms_sold=9, rooms_out_of_service=1).occupancy == 1.0


def test_night_without_out_of_service_count_uses_all_rooms() -> None:
    assert night(rooms_sold=9, rooms_out_of_service=None).occupancy == 0.9


def test_no_sellable_rooms_has_no_occupancy() -> None:
    assert night(rooms_sold=0, rooms_out_of_service=10).occupancy is None


# Saving


async def test_sample_saves_new_columns_and_reloads_unchanged(session, priced) -> None:
    hotel = await session.get(Hotel, priced.hotel_id)
    [parsed] = performance.parse_files([("Actual & Forecast.csv", SAMPLE)])
    base_rate = Decimal("150")

    await performance.save_file(session, hotel, parsed, base_rate=base_rate)
    again = await performance.save_file(session, hotel, parsed, base_rate=base_rate)

    assert again[Outcome.UNCHANGED] == 14
    first = await session.scalar(
        select(DailyPerformance).where(DailyPerformance.stay_date == date(2025, 9, 1))
    )
    assert first.rooms_out_of_service == 1
    assert first.rooms_blocked == 0
    assert first.waitlist == 0
