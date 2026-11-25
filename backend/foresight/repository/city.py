from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.city import City


async def create_city(session: AsyncSession, **values: Any) -> City | None:
    """Inserts a city.

    Args:
        session (AsyncSession): The database session.
        **values (Any): The city's columns, including its slug.

    Returns:
        City | None: The new city, or None if its slug is taken.
    """
    return await session.scalar(
        insert(City)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_cities_slug")
        .returning(City)
    )


async def get_city(session: AsyncSession, city_id: int) -> City | None:
    """Gets a city.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.

    Returns:
        City | None: The city, or None if it doesn't exist.
    """
    return await session.get(City, city_id)


async def list_cities(session: AsyncSession) -> Sequence[City]:
    """Lists every city.

    Args:
        session (AsyncSession): The database session.

    Returns:
        Sequence[City]: The cities, by name.
    """
    return (await session.scalars(select(City).order_by(City.name))).all()


async def update_city(
    session: AsyncSession, city_id: int, changes: Mapping[str, Any]
) -> City | None:
    """Changes a city's columns.

    Runs in a savepoint, so a rejected rename leaves the caller's transaction
    usable.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        changes (Mapping[str, Any]): The columns to change.

    Returns:
        City | None: The city, or None if the new slug is taken.
    """
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
