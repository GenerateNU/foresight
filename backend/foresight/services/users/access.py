from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.user import User
from foresight.repository import job as job_repo
from foresight.repository import model as model_repo
from foresight.repository import user as user_repo
from foresight.services.errors import NotFoundError


async def require_hotel(session: AsyncSession, user: User, hotel_id: int) -> None:
    """Checks the user is linked to a hotel.

    A hotel is reachable only through a link in `user_hotels`. Every check
    here raises the same NotFoundError whether the thing doesn't exist or
    belongs to someone else, so a 404 never reveals which ids are real.

    Args:
        session (AsyncSession): The database session.
        user (User): The signed-in user.
        hotel_id (int): The hotel.

    Raises:
        NotFoundError: The user isn't linked to it, or it doesn't exist.
    """
    if not await user_repo.has_hotel(session, user.id, hotel_id):
        raise NotFoundError("Hotel", hotel_id)


async def require_job(session: AsyncSession, user: User, job_id: int) -> None:
    """Checks the job belongs to one of the user's hotels.

    Args:
        session (AsyncSession): The database session.
        user (User): The signed-in user.
        job_id (int): The job.

    Raises:
        NotFoundError: It isn't theirs, or it doesn't exist.
    """
    job = await job_repo.get_job(session, job_id)
    if job is None or not await user_repo.has_hotel(session, user.id, job.hotel_id):
        raise NotFoundError("Job", job_id)


async def require_model(session: AsyncSession, user: User, model_id: int) -> None:
    """Checks the model version belongs to one of the user's hotels.

    Args:
        session (AsyncSession): The database session.
        user (User): The signed-in user.
        model_id (int): The model version.

    Raises:
        NotFoundError: It isn't theirs, or it doesn't exist.
    """
    version_row = await model_repo.get_model(session, model_id)
    if version_row is None or not await user_repo.has_hotel(
        session, user.id, version_row.hotel_id
    ):
        raise NotFoundError("Pricing model", model_id)


async def require_city_member(session: AsyncSession, user: User, city_id: int) -> None:
    """Checks the user works at a hotel in the city.

    A city is shared by every hotel in it, so only someone who works in it may
    change it.

    Args:
        session (AsyncSession): The database session.
        user (User): The signed-in user.
        city_id (int): The city.

    Raises:
        NotFoundError: They don't, or the city doesn't exist.
    """
    if not await user_repo.has_hotel_in_city(session, user.id, city_id):
        raise NotFoundError("City", city_id)
