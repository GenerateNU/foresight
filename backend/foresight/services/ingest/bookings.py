"""Guestline bookings and cancellations: parse an uploaded file, then save it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import booking as booking_repo
from foresight.repository import hotel as hotel_repo
from foresight.services.adapters import guestline
from foresight.services.errors import InvalidRequestError, NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.repository.upsert import Outcome
    from foresight.services.adapters.guestline import Parsed


def parse_bookings(name: str, content: bytes) -> Parsed:
    try:
        return guestline.parse_bookings(content)
    except guestline.PARSE_ERRORS as exc:
        raise InvalidRequestError(f"could not import {name}: {exc}") from exc


def parse_cancellations(name: str, content: bytes) -> Parsed:
    try:
        return guestline.parse_cancellations(content)
    except guestline.PARSE_ERRORS as exc:
        raise InvalidRequestError(f"could not import {name}: {exc}") from exc


async def save_bookings(
    session: AsyncSession, hotel_id: int, parsed: Parsed
) -> dict[Outcome, int]:
    """Save a file's bookings for a hotel. Does not commit."""
    await _check_hotel(session, hotel_id)
    rows = [{**row, "hotel_id": hotel_id} for row in parsed.rows]
    return await booking_repo.upsert_bookings(session, rows)


async def save_cancellations(
    session: AsyncSession, hotel_id: int, parsed: Parsed
) -> dict[Outcome, int]:
    """Save a file's cancellations for a hotel. Does not commit."""
    await _check_hotel(session, hotel_id)
    rows = [{**row, "hotel_id": hotel_id} for row in parsed.rows]
    return await booking_repo.upsert_cancellations(session, rows)


async def _check_hotel(session: AsyncSession, hotel_id: int) -> None:
    if await hotel_repo.get_hotel(session, hotel_id) is None:
        raise NotFoundError("Hotel", hotel_id)
