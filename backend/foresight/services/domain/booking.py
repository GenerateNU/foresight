"""Bookings: how many rooms were booked for a night on any earlier date."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import booking as booking_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession


async def rooms_booked(
    session: AsyncSession, hotel_id: int, *, night: date, as_of: date
) -> int:
    """Rooms booked for `night` at the end of `as_of` (decision 0047)."""
    await get_hotel(session, hotel_id)
    live = await booking_repo.list_live_bookings(
        session, hotel_id, start=night, end=night
    )
    cancellations = await booking_repo.list_cancellations(
        session, hotel_id, start=night, end=night
    )

    made_by_then = sum(b.booked_at.date() <= as_of for b in live)
    # A set: a room can have two cancellation rows.
    not_yet_cancelled = {
        c.book_ref
        for c in cancellations
        if c.booked_at.date() <= as_of and c.cancelled_at.date() > as_of
    }
    return made_by_then + len(not_yet_cancelled)
