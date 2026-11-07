"""Guestline Daily New Reservations and Cancellations: parse an uploaded file,
then save its rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from foresight.repository import booking as booking_repo
from foresight.services.adapters.hotel import cancellations, reservations

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.repository.upsert import Outcome

PARSE_ERRORS = reservations.PARSE_ERRORS

RESERVATION_COLUMNS = reservations.COLUMNS
CANCELLATION_COLUMNS = cancellations.COLUMNS
# The date each export is filtered by (decision 0031).
RESERVATION_DATE_FIELD = "booked_at"
CANCELLATION_DATE_FIELD = "cancelled_at"


def parse_reservations(
    content: bytes,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    parsed = reservations.parse(content)
    return parsed.rows, parsed.skipped, {}


def parse_cancellations(
    content: bytes,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    parsed = cancellations.parse(content)
    return parsed.rows, parsed.skipped, {}


async def save_reservations(
    session: AsyncSession,
    hotel: Hotel,
    rows: Sequence[Mapping[str, Any]],
    _: Mapping[str, Any],
) -> dict[Outcome, int]:
    """Save bookings for a hotel. Does not commit."""
    return await booking_repo.upsert_bookings(
        session, [{**row, "hotel_id": hotel.id} for row in rows]
    )


async def save_cancellations(
    session: AsyncSession,
    hotel: Hotel,
    rows: Sequence[Mapping[str, Any]],
    _: Mapping[str, Any],
) -> dict[Outcome, int]:
    """Save cancellations for a hotel. Does not commit."""
    return await booking_repo.upsert_cancellations(
        session, [{**row, "hotel_id": hotel.id} for row in rows]
    )
