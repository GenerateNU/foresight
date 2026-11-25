from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.booking import Booking, BookingCancellation
from foresight.repository.upsert import Outcome, upsert_rows


async def upsert_bookings(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Saves bookings keyed on the hotel and Guestline's reference.

    Loading the same file twice changes nothing.

    Args:
        session (AsyncSession): The database session.
        rows (Iterable[Mapping[str, Any]]): One booking per row, with every
            column but `id`.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
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
    """Saves cancellations keyed on the hotel and Guestline's reference.

    Args:
        session (AsyncSession): The database session.
        rows (Iterable[Mapping[str, Any]]): One cancellation per row, with
            every column but `id`.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
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
    """Lists bookings with a night in a window and no cancellation.

    A cancellation matches on the booking's reference alone, since it can
    carry amended stay dates.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        room_type_code (str | None): Only this room code; None for any.
        rate_plan (str | None): Only this rate plan; None for any.

    Returns:
        Sequence[Booking]: The live bookings.
    """
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
    """Finds the first and last night any booking covers.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        room_type_code (str | None): Only this room code; None for any.
        rate_plan (str | None): Only this rate plan; None for any.

    Returns:
        tuple[date, date] | None: The first night and the last (the day
            before the latest departure), or None without bookings.
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
    """Narrows a query to one room code and rate plan, where given.

    Args:
        stmt (S): A query over bookings.
        room_type_code (str | None): The room code; None for any.
        rate_plan (str | None): The rate plan; None for any.

    Returns:
        S: The narrowed query.
    """
    if room_type_code is not None:
        stmt = stmt.where(Booking.room_type_code == room_type_code)
    if rate_plan is not None:
        stmt = stmt.where(Booking.rate_plan == rate_plan)
    return stmt


def _stays_touching[T: (Booking, BookingCancellation)](
    model: type[T], hotel_id: int, start: date, end: date
) -> Select[tuple[T]]:
    """Selects the hotel's stays with at least one night in a window.

    Args:
        model (type[T]): Booking or BookingCancellation.
        hotel_id (int): The hotel.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        Select[tuple[T]]: The query.
    """
    return select(model).where(
        model.hotel_id == hotel_id, model.arrival <= end, model.departure > start
    )
