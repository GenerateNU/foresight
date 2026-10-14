"""A hotel's nightly performance, parsed from client CSV exports and saved."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from foresight.repository import hotel as hotel_repo
from foresight.services.adapters.hotel_csv import (
    PARSE_ERRORS,
    ROOM_TYPE,
    HotelDataParser,
)
from foresight.services.errors import InvalidRequestError

if TYPE_CHECKING:
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.repository.upsert import Outcome


@dataclass(frozen=True, slots=True)
class ParsedFile:
    name: str
    nights: list[dict[str, Any]]  # `daily_performance` rows minus room_type_id
    total_rooms: int


def parse_files(files: list[tuple[str, bytes]]) -> list[ParsedFile]:
    """Parse every file before anything is saved.

    Raises:
        InvalidRequestError: Naming the first file that doesn't parse.
    """
    parsed = []
    for name, content in files:
        parser = HotelDataParser(io.BytesIO(content))
        try:
            parser.run()
        except PARSE_ERRORS as exc:
            raise InvalidRequestError(f"could not import {name}: {exc}") from exc
        parsed.append(
            ParsedFile(name, parser.rows(room_type_id=None), parser.total_rooms())
        )
    return parsed


async def save_file(
    session: AsyncSession, hotel: Hotel, parsed: ParsedFile, *, base_rate: Decimal
) -> dict[Outcome, int]:
    """Upsert one file's nights onto the hotel's standard room type.

    The room type is created on first import; its room count follows the
    file. Re-importing the same file changes nothing. Does not commit.
    """
    room_type_id = await hotel_repo.upsert_room_type(
        session,
        hotel_id=hotel.id,
        name=ROOM_TYPE,
        room_count=parsed.total_rooms,
        base_rate=base_rate,
    )
    return await hotel_repo.upsert_daily_performance(
        session, [{**night, "room_type_id": room_type_id} for night in parsed.nights]
    )
