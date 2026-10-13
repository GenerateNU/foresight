from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.repository import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from decimal import Decimal

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

_PERF_KEY = ("room_type_id", "stay_date")
_PERF_MEASURES = ("rate", "rooms_available", "rooms_sold", "room_revenue")


async def get_hotel(session: AsyncSession, hotel_id: int) -> Hotel | None:
    return await session.get(Hotel, hotel_id)


async def upsert_hotel(
    session: AsyncSession,
    *,
    name: str,
    city: str,
    total_rooms: int,
    latitude: float | None = None,
    longitude: float | None = None,
) -> int:
    """Return the id of the hotel named `name` in `city`, creating it if new."""
    stmt = insert(Hotel).values(
        name=name,
        city=city,
        total_rooms=total_rooms,
        latitude=latitude,
        longitude=longitude,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_hotels_name_city",
        set_={
            "total_rooms": stmt.excluded.total_rooms,
            # Coordinates are optional, so a caller that omits them must not
            # erase what another caller already stored.
            "latitude": func.coalesce(stmt.excluded.latitude, Hotel.latitude),
            "longitude": func.coalesce(stmt.excluded.longitude, Hotel.longitude),
        },
    ).returning(Hotel.id)
    return (await session.execute(stmt)).scalar_one()


async def upsert_room_type(
    session: AsyncSession,
    *,
    hotel_id: int,
    name: str,
    room_count: int,
    base_rate: Decimal,
) -> int:
    stmt = insert(RoomType).values(
        hotel_id=hotel_id, name=name, room_count=room_count, base_rate=base_rate
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_room_types_hotel_name",
        set_={
            "room_count": stmt.excluded.room_count,
            # The pricing model scales off base_rate, so a reload correcting it
            # has to win rather than be silently dropped.
            "base_rate": stmt.excluded.base_rate,
        },
    ).returning(RoomType.id)
    return (await session.execute(stmt)).scalar_one()


async def upsert_daily_performance(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (room_type_id, stay_date)."""
    return await upsert_rows(
        session,
        cast("Table", DailyPerformance.__table__),
        constraint="uq_daily_performance_room_type_stay",
        key=_PERF_KEY,
        mutable=_PERF_MEASURES,
        rows=rows,
    )
