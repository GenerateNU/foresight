from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.hotel import Hotel
from foresight.repository import booking as booking_repo
from foresight.repository.upsert import Outcome
from foresight.services.adapters.hotel import cancellations, reservations

PARSE_ERRORS = reservations.PARSE_ERRORS
RESERVATION_COLUMNS = reservations.COLUMNS
CANCELLATION_COLUMNS = cancellations.COLUMNS
RESERVATION_DATE_FIELD = "booked_at"
CANCELLATION_DATE_FIELD = "cancelled_at"


def parse_reservations(
    content: bytes,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Parses a Daily New Reservations export.

    Args:
        content (bytes): The uploaded file.

    Returns:
        tuple[list[dict[str, Any]], int, dict[str, Any]]: One booking per row,
            how many rows were skipped, and nothing else saving needs.

    Raises:
        ValueError: The file isn't this report, or no row can be read.
    """
    parsed = reservations.parse(content)
    return parsed.rows, parsed.skipped, {}


def parse_cancellations(
    content: bytes,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Parses a Cancellations export.

    Args:
        content (bytes): The uploaded file.

    Returns:
        tuple[list[dict[str, Any]], int, dict[str, Any]]: One cancellation per
            row, how many rows were skipped, and nothing else saving needs.

    Raises:
        ValueError: The file isn't this report, or no row can be read.
    """
    parsed = cancellations.parse(content)
    return parsed.rows, parsed.skipped, {}


async def save_reservations(
    session: AsyncSession,
    hotel: Hotel,
    rows: Sequence[Mapping[str, Any]],
    _: Mapping[str, Any],
) -> dict[Outcome, int]:
    """Saves a chunk of bookings for a hotel; does not commit.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        rows (Sequence[Mapping[str, Any]]): Parsed bookings.
        _ (Mapping[str, Any]): Unused; every report's save takes it.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
    return await booking_repo.upsert_bookings(
        session, [{**row, "hotel_id": hotel.id} for row in rows]
    )


async def save_cancellations(
    session: AsyncSession,
    hotel: Hotel,
    rows: Sequence[Mapping[str, Any]],
    _: Mapping[str, Any],
) -> dict[Outcome, int]:
    """Saves a chunk of cancellations for a hotel; does not commit.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        rows (Sequence[Mapping[str, Any]]): Parsed cancellations.
        _ (Mapping[str, Any]): Unused; every report's save takes it.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
    return await booking_repo.upsert_cancellations(
        session, [{**row, "hotel_id": hotel.id} for row in rows]
    )
