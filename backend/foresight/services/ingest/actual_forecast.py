"""Guestline Actual & Forecast: parse an uploaded file, then save its nights."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from foresight.repository import hotel as hotel_repo
from foresight.services.adapters.hotel.actual_forecast import (
    PARSE_ERRORS,
    ROOM_TYPE,
    HotelDataParser,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.repository.upsert import Outcome

__all__ = ["COLUMNS", "DATE_FIELD", "PARSE_ERRORS", "parse", "save"]

# What marks a file as this report: every column the parser needs.
COLUMNS = ["Date", "InStock", "Total", "Accomm"]
# The date each row is filtered by in the export (decision 0031).
DATE_FIELD = "stay_date"


def parse(content: bytes) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Nights as `daily_performance` rows minus room_type_id, the rows
    skipped (always 0: a bad night rejects the file), and the hotel's room
    count for the room type."""
    parser = HotelDataParser(io.BytesIO(content))
    parser.run()
    nights = parser.rows(room_type_id=None)
    for night in nights:
        del night["room_type_id"]
    return nights, 0, {"total_rooms": parser.total_rooms()}


async def save(
    session: AsyncSession,
    hotel: Hotel,
    rows: Sequence[Mapping[str, Any]],
    extra: Mapping[str, Any],
) -> dict[Outcome, int]:
    """Upsert nights onto the hotel's standard room type.

    The room type is created on first import; its room count follows the
    file. Re-importing the same file changes nothing. Does not commit.
    """
    room_type_id = await hotel_repo.upsert_room_type(
        session, hotel_id=hotel.id, name=ROOM_TYPE, room_count=extra["total_rooms"]
    )
    return await hotel_repo.upsert_daily_performance(
        session, [{**night, "room_type_id": room_type_id} for night in rows]
    )
