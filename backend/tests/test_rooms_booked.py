"""How many rooms were booked for a night as of an earlier date (decision 0047):
bookings made by that date with no cancellation, plus cancelled bookings made by
that date and cancelled after it.

Uses the rolled-back `session`, so the repository read is tested with the rule.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from foresight.database.models import Hotel
from foresight.repository import booking as booking_repo
from foresight.services.domain import booking as service
from foresight.services.errors import NotFoundError

AS_OF = date(2025, 9, 1)
NIGHT = date(2025, 9, 10)
LONG_AGO = datetime(2025, 6, 1, 12, 0)
LONG_AFTER = datetime(2025, 9, 8, 12, 0)


def booking(
    book_ref: str = "BK1/1",
    *,
    booked_at: datetime = LONG_AGO,
    arrival: date = NIGHT,
    departure: date = NIGHT + timedelta(days=1),
) -> dict:
    return {
        "book_ref": book_ref,
        "booked_at": booked_at,
        "arrival": arrival,
        "departure": departure,
        "nights": (departure - arrival).days,
        "room_type_code": "DOUBLE",
        "company_code": None,
        "agent_code": None,
        "adr_nett": Decimal("100.00"),
        "value_nett": Decimal("100.00"),
        "rate_plan": None,
        "market_segment": None,
    }


def cancellation(
    book_ref: str = "BK1/1",
    *,
    cancel_ref: str | None = None,
    booked_at: datetime = LONG_AGO,
    cancelled_at: datetime = LONG_AFTER,
    arrival: date = NIGHT,
    departure: date = NIGHT + timedelta(days=1),
) -> dict:
    return {
        "cancel_ref": cancel_ref or f"CN-{book_ref}",
        "book_ref": book_ref,
        "booked_at": booked_at,
        "cancelled_at": cancelled_at,
        "reason_code": None,
        "arrival": arrival,
        "departure": departure,
        "lost_revenue": Decimal("100.00"),
    }


async def save(session, hotel_id: int, *rows: dict) -> None:
    """Store rows made by `booking` and `cancellation`, in either table."""
    with_hotel = [{**row, "hotel_id": hotel_id} for row in rows]
    live = [row for row in with_hotel if "cancel_ref" not in row]
    cancelled = [row for row in with_hotel if "cancel_ref" in row]
    await booking_repo.upsert_bookings(session, live)
    await booking_repo.upsert_cancellations(session, cancelled)


async def rooms(session, hotel_id: int, *, night=NIGHT, as_of=AS_OF) -> int:
    return await service.rooms_booked(session, hotel_id, night=night, as_of=as_of)


# Live bookings


@pytest.mark.parametrize(
    ("booked_at", "expected"),
    [
        (LONG_AGO, 1),
        (datetime(2025, 9, 1, 0, 0), 1),  # the as-of date counts, all of it
        (datetime(2025, 9, 1, 23, 59, 59), 1),
        (datetime(2025, 9, 2, 0, 0), 0),
        (LONG_AFTER, 0),
    ],
)
async def test_live_booking_counts_once_made(session, priced, booked_at, expected):
    await save(session, priced.hotel_id, booking(booked_at=booked_at))

    assert await rooms(session, priced.hotel_id) == expected


async def test_every_room_on_a_booking_counts(session, priced) -> None:
    await save(session, priced.hotel_id, booking("BK1/1"), booking("BK1/2"))

    assert await rooms(session, priced.hotel_id) == 2


# Cancelled bookings


@pytest.mark.parametrize(
    ("cancelled_at", "expected"),
    [
        (datetime(2025, 8, 31, 23, 59, 59), 0),
        (datetime(2025, 9, 1, 0, 0), 0),  # cancelled on the as-of date
        (datetime(2025, 9, 1, 23, 59, 59), 0),
        (datetime(2025, 9, 2, 0, 0), 1),  # still on the books at the end of the day
        (LONG_AFTER, 1),
    ],
)
async def test_cancelled_booking_counts_until_cancelled(
    session, priced, cancelled_at, expected
):
    await save(session, priced.hotel_id, cancellation(cancelled_at=cancelled_at))

    assert await rooms(session, priced.hotel_id) == expected


async def test_booking_made_after_the_date_and_cancelled_later_is_not_counted(
    session, priced
) -> None:
    row = cancellation(booked_at=datetime(2025, 9, 2, 9, 0))
    await save(session, priced.hotel_id, row)

    assert await rooms(session, priced.hotel_id) == 0


async def test_booked_and_cancelled_on_the_date_is_not_counted(session, priced) -> None:
    row = cancellation(
        booked_at=datetime(2025, 9, 1, 9, 0),
        cancelled_at=datetime(2025, 9, 1, 17, 0),
    )
    await save(session, priced.hotel_id, row)

    assert await rooms(session, priced.hotel_id) == 0


async def test_live_and_cancelled_rooms_add_up(session, priced) -> None:
    await save(session, priced.hotel_id, booking("BK1/1"), cancellation("BK2/1"))

    assert await rooms(session, priced.hotel_id) == 2


# The same room stored twice


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (date(2025, 9, 7), 1),  # not cancelled yet: counted once, not twice
        (date(2025, 9, 8), 0),  # the day it was cancelled
        (date(2025, 9, 9), 0),
    ],
)
async def test_booking_uploaded_live_then_cancelled_counts_once(
    session, priced, as_of, expected
) -> None:
    await save(session, priced.hotel_id, booking(), cancellation())

    assert await rooms(session, priced.hotel_id, as_of=as_of) == expected


@pytest.mark.parametrize(("as_of", "expected"), [(AS_OF, 1), (date(2025, 9, 9), 0)])
async def test_room_cancelled_twice_counts_once(
    session, priced, as_of, expected
) -> None:
    await save(
        session,
        priced.hotel_id,
        cancellation(cancel_ref="CN1/1"),
        cancellation(cancel_ref="CN2/1"),
    )

    assert await rooms(session, priced.hotel_id, as_of=as_of) == expected


async def test_amended_booking_cancelled_on_new_dates_leaves_its_old_night(
    session, priced
) -> None:
    moved_to = {"arrival": date(2025, 9, 20), "departure": date(2025, 9, 21)}
    await save(session, priced.hotel_id, booking(), cancellation(**moved_to))

    assert await rooms(session, priced.hotel_id, as_of=date(2025, 9, 9)) == 0


# Which nights a stay covers


STAY = {"arrival": date(2025, 9, 10), "departure": date(2025, 9, 13)}
STAY_NIGHTS = [
    (date(2025, 9, 9), 0),
    (date(2025, 9, 10), 1),  # arrival
    (date(2025, 9, 12), 1),  # last night
    (date(2025, 9, 13), 0),  # departure: the room isn't slept in
]


@pytest.mark.parametrize(("night", "expected"), STAY_NIGHTS)
async def test_live_stay_covers_arrival_to_the_night_before_departure(
    session, priced, night, expected
) -> None:
    await save(session, priced.hotel_id, booking(**STAY))

    assert await rooms(session, priced.hotel_id, night=night) == expected


@pytest.mark.parametrize(("night", "expected"), STAY_NIGHTS)
async def test_cancelled_stay_covers_the_same_nights(
    session, priced, night, expected
) -> None:
    await save(session, priced.hotel_id, cancellation(**STAY))

    assert await rooms(session, priced.hotel_id, night=night) == expected


# The final count: Guestline's day can run past the stay date, so the day after
# the night is what matches Actual & Forecast.


@pytest.mark.parametrize(("as_of", "expected"), [(NIGHT, 0), (date(2025, 9, 11), 1)])
async def test_booking_dated_the_day_after_arrival_is_in_the_final_count(
    session, priced, as_of, expected
) -> None:
    await save(
        session, priced.hotel_id, booking(booked_at=datetime(2025, 9, 11, 0, 30))
    )

    assert await rooms(session, priced.hotel_id, as_of=as_of) == expected


@pytest.mark.parametrize(("as_of", "expected"), [(NIGHT, 1), (date(2025, 9, 11), 0)])
async def test_no_show_cancelled_the_day_after_is_not_in_the_final_count(
    session, priced, as_of, expected
) -> None:
    row = cancellation(cancelled_at=datetime(2025, 9, 11, 9, 0))
    await save(session, priced.hotel_id, row)

    assert await rooms(session, priced.hotel_id, as_of=as_of) == expected


# Hotels


async def test_other_hotels_are_not_counted(session, priced) -> None:
    hotel = await session.get(Hotel, priced.hotel_id)
    other = Hotel(name="Next Door", city_id=hotel.city_id, total_rooms=20)
    session.add(other)
    await session.flush()
    await save(session, other.id, booking(), cancellation("BK2/1"))

    assert await rooms(session, priced.hotel_id) == 0


async def test_unknown_hotel_is_refused(session) -> None:
    with pytest.raises(NotFoundError):
        await rooms(session, -1)
