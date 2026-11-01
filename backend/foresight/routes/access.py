"""Who is calling, and which hotels they may reach"""

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
    """The signed-in user. A missing, expired or tampered cookie arrives here as
    an empty session, so every case is the same 401."""
    return await user_service.get_signed_in_user(
        session, request.session.get("user_id")
    )


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def _hotel_id(
    hotel_id: Annotated[int, Path(description="The hotel's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    await access_service.require_hotel(session, user, hotel_id)
    return hotel_id


async def _job_id(
    job_id: Annotated[int, Path(description="The job's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    await access_service.require_job(session, user, job_id)
    return job_id


async def _model_id(
    model_id: Annotated[int, Path(description="The model's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    await access_service.require_model(session, user, model_id)
    return model_id


async def _room_type_id(
    room_type_id: Annotated[int, Path(description="The room type's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    await access_service.require_room_type(session, user, room_type_id)
    return room_type_id


async def _editable_city_id(
    city_id: Annotated[int, Path(description="The city's id", examples=[1])],
    user: CurrentUserDep,
    session: SessionDep,
) -> int:
    await access_service.require_city_member(session, user, city_id)
    return city_id


HotelId = Annotated[int, Depends(_hotel_id)]
JobId = Annotated[int, Depends(_job_id)]
ModelId = Annotated[int, Depends(_model_id)]
RoomTypeId = Annotated[int, Depends(_room_type_id)]
EditableCityId = Annotated[int, Depends(_editable_city_id)]
