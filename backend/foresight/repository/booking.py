"""Data access for `bookings` and `booking_cancellations`.

Both are saved with an upsert on the hotel and Guestline's reference, so loading
the same file twice changes nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import exists, select

from foresight.database.models.booking import Booking, BookingCancellation
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_bookings(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    return await upsert_rows(
        session,
        Booking,
        constraint="uq_bookings_hotel_id_book_ref",
        key=("hotel_id", "book_ref"),
        mutable=(
            "booked_at",
            "arrival",
            "departure",
            "nights",
            "room_type_code",
            "company_code",
            "agent_code",
            "adr_nett",
            "value_nett",
            "rate_plan",
            "market_segment",
        ),
        rows=rows,
    )


async def upsert_cancellations(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    return await upsert_rows(
        session,
        BookingCancellation,
        constraint="uq_booking_cancellations_hotel_id_cancel_ref",
        key=("hotel_id", "cancel_ref"),
        mutable=(
            "book_ref",
            "booked_at",
            "cancelled_at",
            "reason_code",
            "arrival",
            "departure",
            "lost_revenue",
        ),
        rows=rows,
    )


async def list_live_bookings(
    session: AsyncSession, hotel_id: int, *, start: date, end: date
) -> Sequence[Booking]:
    """Bookings with a night from `start` to `end` and no cancellation."""
    # Matched on the ref alone: a cancellation can carry amended stay dates.
    cancelled = exists().where(
        BookingCancellation.hotel_id == Booking.hotel_id,
        BookingCancellation.book_ref == Booking.book_ref,
    )
    return (
        await session.scalars(
            select(Booking).where(
                Booking.hotel_id == hotel_id,
                Booking.arrival <= end,
                Booking.departure > start,
                ~cancelled,
            )
        )
    ).all()


async def list_cancellations(
    session: AsyncSession, hotel_id: int, *, start: date, end: date
) -> Sequence[BookingCancellation]:
    """Cancellations with a night from `start` to `end`."""
    return (
        await session.scalars(
            select(BookingCancellation).where(
                BookingCancellation.hotel_id == hotel_id,
                BookingCancellation.arrival <= end,
                BookingCancellation.departure > start,
            )
        )
    ).all()
