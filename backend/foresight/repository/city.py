"""Data access for `cities`.

`create_city` and `update_city` return None when the slug would duplicate
another city's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from foresight.database.models.city import City

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


async def create_city(session: AsyncSession, **values: Any) -> City | None:
    return await session.scalar(
        insert(City)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_cities_slug")
        .returning(City)
    )


async def get_city(session: AsyncSession, city_id: int) -> City | None:
    return await session.get(City, city_id)


async def list_cities(session: AsyncSession) -> Sequence[City]:
    return (await session.scalars(select(City).order_by(City.name))).all()


async def update_city(
    session: AsyncSession, city_id: int, changes: Mapping[str, Any]
) -> City | None:
    """Apply `changes` in a savepoint, so a rejected rename leaves the caller's
    transaction usable."""
    try:
        async with session.begin_nested():
            return await session.scalar(
                update(City)
                .where(City.id == city_id)
                .values(**changes)
                .returning(City)
                .execution_options(populate_existing=True)
            )
    except IntegrityError:
        return None
