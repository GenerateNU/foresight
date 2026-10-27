"""Cities: the markets hotels sit in and every outside signal is keyed on."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from foresight.repository import city as city_repo
from foresight.services.adapters.normalize import slugify_city
from foresight.services.errors import ConflictError, InvalidRequestError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City


async def create_city(session: AsyncSession, *, name: str, **values: Any) -> City:
    """Raises ConflictError if a city with the same normalized name exists."""
    city = await city_repo.create_city(session, name=name, slug=_slug(name), **values)
    if city is None:
        raise ConflictError(f"City {name!r} already exists")
    return city


async def get_city(session: AsyncSession, city_id: int) -> City:
    """Raises NotFoundError for an unknown city."""
    city = await city_repo.get_city(session, city_id)
    if city is None:
        raise NotFoundError("City", city_id)
    return city


async def list_cities(session: AsyncSession) -> Sequence[City]:
    return await city_repo.list_cities(session)


async def update_city(
    session: AsyncSession, city_id: int, changes: dict[str, Any]
) -> City:
    """Change only the fields given. A rename re-derives the slug.

    Events already saved keep the dedupe key built from the old name, so a
    rename is for fixing a typo before ingesting, not for routine use.

    Raises:
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
    """Today where the city is: stay nights are local (decision 0023)."""
    return datetime.now(ZoneInfo(city.timezone)).date()


def _slug(name: str) -> str:
    slug = slugify_city(name)
    if not slug:
        raise InvalidRequestError(f"city name {name!r} has no letters or digits")
    return slug
