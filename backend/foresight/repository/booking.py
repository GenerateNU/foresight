"""Data access for `bookings` and `booking_cancellations`.

Both are saved with an upsert on the hotel and Guestline's reference, so loading
the same file twice changes nothing.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import exists, func, select

from foresight.database.models.booking import Booking, BookingCancellation
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from sqlalchemy import Select
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
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date,
    end: date,
    room_type_code: str | None = None,
    rate_plan: str | None = None,
) -> Sequence[Booking]:
    """Bookings with a night from `start` to `end` and no cancellation; only
    the given room code and rate plan when they're given."""
    # Matched on the ref alone: a cancellation can carry amended stay dates.
    cancelled = exists().where(
        BookingCancellation.hotel_id == Booking.hotel_id,
        BookingCancellation.book_ref == Booking.book_ref,
    )
    stmt = _product(
        _stays_touching(Booking, hotel_id, start, end).where(~cancelled),
        room_type_code,
        rate_plan,
    )
    return (await session.scalars(stmt)).all()


async def booked_night_range(
    session: AsyncSession,
    hotel_id: int,
    *,
    room_type_code: str | None = None,
    rate_plan: str | None = None,
) -> tuple[date, date] | None:
    """The first and last night any booking covers, or None if there are none;
    only the given room code and rate plan when they're given.

    The last night is the day before the latest departure.
    """
    stmt = select(func.min(Booking.arrival), func.max(Booking.departure)).where(
        Booking.hotel_id == hotel_id
    )
    first, departure = (
        await session.execute(_product(stmt, room_type_code, rate_plan))
    ).one()
    if first is None:
        return None
    return first, departure - timedelta(days=1)


def _product[S: Select[Any]](
    stmt: S, room_type_code: str | None, rate_plan: str | None
) -> S:
    """Only bookings of this room code and rate plan, when given."""
    if room_type_code is not None:
        stmt = stmt.where(Booking.room_type_code == room_type_code)
    if rate_plan is not None:
        stmt = stmt.where(Booking.rate_plan == rate_plan)
    return stmt


def _stays_touching[T: (Booking, BookingCancellation)](
    model: type[T], hotel_id: int, start: date, end: date
) -> Select[tuple[T]]:
    return select(model).where(
        model.hotel_id == hotel_id, model.arrival <= end, model.departure > start
    )
