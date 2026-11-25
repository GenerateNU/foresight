from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.city import City
from foresight.repository import city as city_repo
from foresight.services.errors import ConflictError, InvalidRequestError, NotFoundError
from foresight.services.events.normalize import slugify_city


async def create_city(session: AsyncSession, *, name: str, **values: Any) -> City:
    """Creates a city: a market hotels sit in and outside signals are keyed on.

    Args:
        session (AsyncSession): The database session.
        name (str): The city's name.
        **values (Any): Its other columns.

    Returns:
        City: The new city.

    Raises:
        ConflictError: A city with the same normalized name exists.
        InvalidRequestError: The name has no letters or digits.
    """
    city = await city_repo.create_city(session, name=name, slug=_slug(name), **values)
    if city is None:
        raise ConflictError(f"City {name!r} already exists")
    return city


async def get_city(session: AsyncSession, city_id: int) -> City:
    """Gets a city.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.

    Returns:
        City: The city.

    Raises:
        NotFoundError: The city doesn't exist.
    """
    city = await city_repo.get_city(session, city_id)
    if city is None:
        raise NotFoundError("City", city_id)
    return city


async def list_cities(session: AsyncSession) -> Sequence[City]:
    """Lists every city.

    Args:
        session (AsyncSession): The database session.

    Returns:
        Sequence[City]: The cities.
    """
    return await city_repo.list_cities(session)


async def update_city(
    session: AsyncSession, city_id: int, changes: dict[str, Any]
) -> City:
    """Changes only the fields given; a rename re-derives the slug.

    Events already saved keep the dedupe key built from the old name, so a
    rename is for fixing a typo before ingesting, not for routine use.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        changes (dict[str, Any]): New values by column name.

    Returns:
        City: The updated city.

    Raises:
        InvalidRequestError: The new name has no letters or digits.
        NotFoundError: Unknown city.
        ConflictError: The new name normalizes to another city's.
    """
    city = await get_city(session, city_id)
    if not changes:
        return city
    if "name" in changes:
        changes = {**changes, "slug": _slug(changes["name"])}
    updated = await city_repo.update_city(session, city_id, changes)
    if updated is None:
        raise ConflictError(f"City {changes['name']!r} already exists")
    return updated


def local_today(city: City) -> date:
    """Gives today's date in the city; stay nights are local dates.

    Args:
        city (City): The city.

    Returns:
        date: Today there.
    """
    return datetime.now(ZoneInfo(city.timezone)).date()


def local_date(city: City, moment: datetime) -> date:
    """Gives the date in the city at a moment, e.g. when a manager saw a price.

    Args:
        city (City): The city.
        moment (datetime): The moment, with a timezone.

    Returns:
        date: The date there.
    """
    return moment.astimezone(ZoneInfo(city.timezone)).date()


def _slug(name: str) -> str:
    """Builds a city's slug from its name.

    Args:
        name (str): The name.

    Returns:
        str: The slug.

    Raises:
        InvalidRequestError: The name has no letters or digits.
    """
    slug = slugify_city(name)
    if not slug:
        raise InvalidRequestError(f"city name {name!r} has no letters or digits")
    return slug
