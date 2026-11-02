"""Guestline bookings and cancellations: parsing, guest details dropped, bad
rows skipped, and loading the same file twice adding nothing.

Parsing tests need no database. Saving tests use the rolled-back `session`.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from foresight.database.models import Booking, BookingCancellation
from foresight.repository.upsert import Outcome
from foresight.services.adapters import guestline
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ingest import bookings as service

DATA = Path(__file__).parents[1] / "data"
SAMPLE_BOOKINGS = (DATA / "DailyNewReservations.csv").read_bytes()
SAMPLE_CANCELLATIONS = (DATA / "Cancellation.csv").read_bytes()

# One good Daily New Reservations row, with every column the export has.
GOOD = {
    "Site": "Hotel",
    "Company": "",
    "CompanyName": "Acme Ltd",
    "Agent": "",
    "AgentName": "",
    "BookRef": "BK1/1",
    "GuestName": "Jane Doe",
    "Arrival": "03/Sep/2025",
    "Departure": "05/Sep/2025",
    "OperatorCode": "JD",
    "BookingDate": "05/06/2025 16:32:00",
    "Nights": "2",
    "ADRSoldNett": "86.33",
    "ADRSoldGross": "97.98",
    "ReservationValueNett": "172.66",
    "ReservationValueGross": "195.97",
    "CancelledTimeStamp": "",
    "CancelledNights": "0",
    "CancelledRevenueNett": "0.00",
    "CancelledRevenueGross": "0.00",
    "RatePlan": "BAR_RO",
    "MarketSegment": "LEISURE",
    "RoomType": "DOUBLE",
}


def make_csv(*rows: dict) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=GOOD, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


async def count(session, model, hotel_id: int) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(model.hotel_id == hotel_id)
    )


# Parsing


def test_sample_bookings_parse() -> None:
    parsed = guestline.parse_bookings(SAMPLE_BOOKINGS)

    assert parsed.skipped == 0
    assert len(parsed.rows) == 88
    first = parsed.rows[0]
    assert first["book_ref"] == "BK100014/1"
    assert first["booked_at"] == datetime(2025, 6, 5, 16, 32)
    assert first["arrival"] == date(2025, 9, 3)
    assert first["departure"] == date(2025, 9, 5)
    assert first["adr_nett"] == Decimal("86.33")
    assert first["room_type_code"] == "DOUBLE"


def test_sample_cancellations_parse() -> None:
    parsed = guestline.parse_cancellations(SAMPLE_CANCELLATIONS)

    assert parsed.skipped == 0
    assert len(parsed.rows) == 38


def test_guest_details_are_not_kept() -> None:
    row = guestline.parse_bookings(make_csv(GOOD)).rows[0]
    values = {str(v) for v in row.values()}

    assert "Jane Doe" not in values
    assert "JD" not in values
    assert "Acme Ltd" not in values

    for row in guestline.parse_cancellations(SAMPLE_CANCELLATIONS).rows:
        assert not any(str(v).startswith(("Guest", "PF")) for v in row.values())


@pytest.mark.parametrize(
    "bad",
    [
        {"BookRef": ""},
        {"Arrival": "2025-09-03"},
        {"Departure": "03/Sep/2025"},  # same day as arrival
        {"BookingDate": "yesterday"},
        {"ADRSoldNett": "n/a"},
        {"ADRSoldNett": "NaN"},
        {"ADRSoldNett": "Infinity"},
        {"ReservationValueNett": "123456789012.00"},
        {"Nights": ""},
        {"Nights": "99999999999"},
        {"BookRef": "BK" + "1" * 31},
        {"RatePlan": "X" * 65},
    ],
)
def test_bad_row_is_skipped(bad: dict) -> None:
    content = make_csv(GOOD, {**GOOD, "BookRef": "BK2/1", **bad})
    parsed = guestline.parse_bookings(content)

    assert parsed.skipped == 1
    assert [row["book_ref"] for row in parsed.rows] == ["BK1/1"]


def test_short_row_is_skipped() -> None:
    content = make_csv(GOOD) + b'"Hotel","","","","","BK9/1"\n'

    assert guestline.parse_bookings(content).skipped == 1


def test_wrong_report_is_rejected() -> None:
    with pytest.raises(InvalidRequestError):
        service.parse_bookings("Cancellation.csv", SAMPLE_CANCELLATIONS)


def test_file_with_no_readable_rows_is_rejected() -> None:
    content = make_csv({**GOOD, "Arrival": "03/09/2025"})

    with pytest.raises(InvalidRequestError):
        service.parse_bookings("DailyNewReservations.csv", content)


def test_header_only_file_loads_empty() -> None:
    parsed = service.parse_bookings("DailyNewReservations.csv", make_csv())

    assert parsed.rows == []


# Saving


async def test_loading_twice_adds_nothing(session, priced) -> None:
    bookings = guestline.parse_bookings(SAMPLE_BOOKINGS)
    cancellations = guestline.parse_cancellations(SAMPLE_CANCELLATIONS)

    await service.save_bookings(session, priced.hotel_id, bookings)
    await service.save_cancellations(session, priced.hotel_id, cancellations)
    second = await service.save_bookings(session, priced.hotel_id, bookings)
    second_cancellations = await service.save_cancellations(
        session, priced.hotel_id, cancellations
    )

    assert second[Outcome.NEW] == 0
    assert second[Outcome.UNCHANGED] == 88
    assert second_cancellations[Outcome.UNCHANGED] == 38
    assert await count(session, Booking, priced.hotel_id) == 88
    assert await count(session, BookingCancellation, priced.hotel_id) == 38


async def test_changed_row_is_updated(session, priced) -> None:
    await service.save_bookings(
        session, priced.hotel_id, guestline.parse_bookings(make_csv(GOOD))
    )
    changed = guestline.parse_bookings(make_csv({**GOOD, "ADRSoldNett": "99.00"}))
    result = await service.save_bookings(session, priced.hotel_id, changed)

    assert result[Outcome.UPDATED] == 1
    stored = select(Booking.adr_nett).where(Booking.hotel_id == priced.hotel_id)
    assert await session.scalar(stored) == Decimal("99.00")


async def test_unknown_hotel_is_refused(session) -> None:
    with pytest.raises(NotFoundError):
        await service.save_bookings(
            session, -1, guestline.parse_bookings(SAMPLE_BOOKINGS)
        )
