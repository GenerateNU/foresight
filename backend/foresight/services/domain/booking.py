"""Bookings: how many rooms were booked for a night on any earlier date."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from foresight.repository import booking as booking_repo
from foresight.repository import hotel as hotel_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.booking import Booking, BookingCancellation


@dataclass(frozen=True, slots=True)
class FinalCountCheck:
    nights: int  # nights with a final count to compare
    mismatches: dict[date, int]  # night -> rooms rebuilt minus rooms sold


async def rooms_booked(
    session: AsyncSession, hotel_id: int, *, night: date, as_of: date
) -> int:
    """Rooms booked for `night` at the end of `as_of` (decision 0047)."""
    curves = await booking_curves(session, hotel_id, start=night, end=night)
    return rooms_on(curves.get(night, {}), as_of)


async def booking_curves(
    session: AsyncSession, hotel_id: int, *, start: date, end: date
) -> dict[date, dict[date, int]]:
    """Rooms booked for each night from `start` to `end`, by day.

    A night maps each day its count changed, oldest first, to the count at the
    end of that day. Read one with `rooms_on`. Nights with no rooms are left out.
    """
    await get_hotel(session, hotel_id)
    live = await booking_repo.list_live_bookings(
        session, hotel_id, start=start, end=end
    )
    cancellations = await booking_repo.list_cancellations(
        session, hotel_id, start=start, end=end
    )

    changes: defaultdict[date, Counter[date]] = defaultdict(Counter)
    for booking in live:
        for night in _nights(booking, start, end):
            changes[night][booking.booked_at.date()] += 1
    # One per ref: a room can have two cancellation rows.
    latest = {
        c.book_ref: c for c in sorted(cancellations, key=lambda c: c.cancelled_at)
    }
    for cancellation in latest.values():
        for night in _nights(cancellation, start, end):
            changes[night][cancellation.booked_at.date()] += 1
            changes[night][cancellation.cancelled_at.date()] -= 1

    return {night: _running_total(days) for night, days in changes.items()}


async def check_final_counts(
    session: AsyncSession, hotel_id: int, *, start: date, end: date
) -> FinalCountCheck:
    """Compare the rebuild with rooms sold on each night from `start` to `end`.

    Pass a `start` the booking export fully covers, or early nights run short.
    """
    curves = await booking_curves(session, hotel_id, start=start, end=end)
    sold: Counter[date] = Counter()
    for row in await hotel_repo.list_nights(session, hotel_id, start=start, end=end):
        sold[row["stay_date"]] += row["rooms_sold"]

    # The day after: late bookings and no-shows can be dated after the stay night.
    differences = {
        night: rooms_on(curves.get(night, {}), night + timedelta(days=1)) - rooms
        for night, rooms in sold.items()
    }
    return FinalCountCheck(
        nights=len(sold),
        mismatches={night: gap for night, gap in differences.items() if gap},
    )


def rooms_on(curve: dict[date, int], as_of: date) -> int:
    """A night's rooms booked at the end of `as_of`, from its `booking_curves`."""
    days = list(curve)
    changes_so_far = bisect_right(days, as_of)
    return curve[days[changes_so_far - 1]] if changes_so_far else 0


def _nights(
    stay: Booking | BookingCancellation, start: date, end: date
) -> Iterator[date]:
    night = max(stay.arrival, start)
    while night < stay.departure and night <= end:
        yield night
        night += timedelta(days=1)


def _running_total(changes: Counter[date]) -> dict[date, int]:
    total = 0
    curve = {}
    for day in sorted(changes):
        total += changes[day]
        curve[day] = total
    return curve
