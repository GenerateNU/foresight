"""Which hotel data a user may reach.

A hotel is reachable only through a link in `user_hotels`. Every check raises
the same NotFoundError whether the thing doesn't exist or belongs to someone
else, so a 404 never reveals which ids are real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import hotel as hotel_repo
from foresight.repository import job as job_repo
from foresight.repository import pricing_model as model_repo
from foresight.repository import user as user_repo
from foresight.services.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.user import User


async def require_hotel(session: AsyncSession, user: User, hotel_id: int) -> None:
    """Raises NotFoundError unless the user is linked to this hotel."""
    if not await user_repo.has_hotel(session, user.id, hotel_id):
        raise NotFoundError("Hotel", hotel_id)


async def require_job(session: AsyncSession, user: User, job_id: int) -> None:
    """Raises NotFoundError unless the job is one of the user's hotels'."""
    job = await job_repo.get_job(session, job_id)
    if job is None or not await user_repo.has_hotel(session, user.id, job.hotel_id):
        raise NotFoundError("Job", job_id)


async def require_model(session: AsyncSession, user: User, model_id: int) -> None:
    """Raises NotFoundError unless the model is one of the user's hotels'."""
    model = await model_repo.get_pricing_model(session, model_id)
    if model is None or not await user_repo.has_hotel(session, user.id, model.hotel_id):
        raise NotFoundError("Pricing model", model_id)


async def require_room_type(
    session: AsyncSession, user: User, room_type_id: int
) -> None:
    """Raises NotFoundError unless the room type is one of the user's hotels'."""
    room_type = await hotel_repo.get_room_type(session, room_type_id)
    if room_type is None or not await user_repo.has_hotel(
        session, user.id, room_type.hotel_id
    ):
        raise NotFoundError("Room type", room_type_id)


async def require_city_member(session: AsyncSession, user: User, city_id: int) -> None:
    """Raises NotFoundError unless the user is linked to a hotel in this city.

    A city is shared by every hotel in it, so only someone who works in it may
    change it.
    """
    if not await user_repo.has_hotel_in_city(session, user.id, city_id):
        raise NotFoundError("City", city_id)
