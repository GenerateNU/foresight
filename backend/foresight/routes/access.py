from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import APIKeyCookie

from foresight.database.models.user import User
from foresight.routes.helpers import SessionDep
from foresight.services.domain import access as access_service
from foresight.services.domain import user as user_service

SESSION_COOKIE = "foresight_session"

_cookie_scheme = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Set by signing in at /auth/google/login",
)


async def get_current_user(
    request: Request,
    session: SessionDep,
    _cookie: Annotated[str | None, Depends(_cookie_scheme)] = None,
) -> User:
    """Gets the signed-in user.

    A missing, expired or tampered cookie arrives here as an empty session, so
    every case is the same 401.

    Args:
        request (Request): The request, with its session.
        session (SessionDep): The database session.
        _cookie (str | None): Declares the cookie, so /docs can send it.

    Returns:
        User: The user.

    Raises:
        NotSignedInError: No valid session.
    """
    return await user_service.get_signed_in_user(
        session, request.session.get("user_id")
    )


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def _hotel_id(
    hotel_id: Annotated[int, Path(description="The hotel's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    """Checks the signed-in user may reach a hotel in the path.

    Args:
        hotel_id (int): The hotel.
        user (CurrentUserDep): The signed-in user.
        session (SessionDep): The database session.

    Returns:
        int: The hotel's id.

    Raises:
        NotFoundError: They may not, or it doesn't exist.
    """
    await access_service.require_hotel(session, user, hotel_id)
    return hotel_id


async def _job_id(
    job_id: Annotated[int, Path(description="The job's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    """Checks the signed-in user may reach a job in the path.

    Args:
        job_id (int): The job.
        user (CurrentUserDep): The signed-in user.
        session (SessionDep): The database session.

    Returns:
        int: The job's id.

    Raises:
        NotFoundError: They may not, or it doesn't exist.
    """
    await access_service.require_job(session, user, job_id)
    return job_id


async def _model_id(
    model_id: Annotated[int, Path(description="The model's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    """Checks the signed-in user may reach a model version in the path.

    Args:
        model_id (int): The version.
        user (CurrentUserDep): The signed-in user.
        session (SessionDep): The database session.

    Returns:
        int: The version's id.

    Raises:
        NotFoundError: They may not, or it doesn't exist.
    """
    await access_service.require_model(session, user, model_id)
    return model_id


async def _editable_city_id(
    city_id: Annotated[int, Path(description="The city's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    """Checks the signed-in user may change a city in the path.

    Args:
        city_id (int): The city.
        user (CurrentUserDep): The signed-in user.
        session (SessionDep): The database session.

    Returns:
        int: The city's id.

    Raises:
        NotFoundError: They don't work in it, or it doesn't exist.
    """
    await access_service.require_city_member(session, user, city_id)
    return city_id


HotelId = Annotated[int, Depends(_hotel_id)]
JobId = Annotated[int, Depends(_job_id)]
ModelId = Annotated[int, Depends(_model_id)]
EditableCityId = Annotated[int, Depends(_editable_city_id)]
