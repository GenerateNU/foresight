"""HTTP layer for hotels, their room types, performance and recommendations."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from foresight.routes.common import PageDep, SessionDep, not_found, paginate
from foresight.schemas.common import Page
from foresight.schemas.hotel import (
    DailyPerformanceRead,
    HotelCreate,
    HotelRead,
    RoomTypeCreate,
    RoomTypeRead,
)
from foresight.schemas.recommendation import RecommendationRead
from foresight.services import hotel as hotel_service
from foresight.services import recommendation as recommendation_service

router = APIRouter(tags=["hotels"])


@router.post("/hotels", response_model=HotelRead, status_code=status.HTTP_201_CREATED)
async def create_hotel(data: HotelCreate, session: SessionDep) -> HotelRead:
    hotel = await hotel_service.create_hotel(session, data)
    return HotelRead.model_validate(hotel)


@router.get("/hotels", response_model=Page[HotelRead])
async def list_hotels(session: SessionDep, page: PageDep) -> Page[HotelRead]:
    hotels, total = await hotel_service.list_hotels(
        session, limit=page.limit, offset=page.offset
    )
    return paginate(HotelRead, hotels, total, page)


@router.get("/hotels/{hotel_id}", response_model=HotelRead)
async def get_hotel(hotel_id: int, session: SessionDep) -> HotelRead:
    hotel = await hotel_service.get_hotel(session, hotel_id)
    if hotel is None:
        raise not_found("Hotel", hotel_id)
    return HotelRead.model_validate(hotel)


@router.post(
    "/room-types", response_model=RoomTypeRead, status_code=status.HTTP_201_CREATED
)
async def create_room_type(data: RoomTypeCreate, session: SessionDep) -> RoomTypeRead:
    room_type = await hotel_service.create_room_type(session, data)
    if room_type is None:
        raise not_found("Hotel", data.hotel_id)
    return RoomTypeRead.model_validate(room_type)


@router.get("/room-types/{room_type_id}", response_model=RoomTypeRead)
async def get_room_type(room_type_id: int, session: SessionDep) -> RoomTypeRead:
    room_type = await hotel_service.get_room_type(session, room_type_id)
    if room_type is None:
        raise not_found("Room type", room_type_id)
    return RoomTypeRead.model_validate(room_type)


@router.get("/hotels/{hotel_id}/room-types", response_model=Page[RoomTypeRead])
async def list_room_types(
    hotel_id: int, session: SessionDep, page: PageDep
) -> Page[RoomTypeRead]:
    result = await hotel_service.list_room_types(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    if result is None:
        raise not_found("Hotel", hotel_id)
    room_types, total = result
    return paginate(RoomTypeRead, room_types, total, page)


@router.get("/hotels/{hotel_id}/performance", response_model=Page[DailyPerformanceRead])
async def list_performance(
    hotel_id: int,
    session: SessionDep,
    page: PageDep,
    start: date | None = None,
    end: date | None = None,
    room_type_id: int | None = None,
) -> Page[DailyPerformanceRead]:
    """Nightly performance across the hotel's room types; `start`/`end` inclusive."""
    result = await hotel_service.list_performance(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_id=room_type_id,
        limit=page.limit,
        offset=page.offset,
    )
    if result is None:
        raise not_found("Hotel", hotel_id)
    nights, total = result
    return paginate(DailyPerformanceRead, nights, total, page)


@router.get("/hotels/{hotel_id}/recommendations", response_model=RecommendationRead)
async def get_recommendation(
    hotel_id: int,
    session: SessionDep,
    # Named `stay_date` in code because `date` is the type; the query key stays `date`.
    stay_date: Annotated[date, Query(alias="date")],
) -> RecommendationRead:
    """Placeholder rate for one night, in the final response shape."""
    recommendation = await recommendation_service.get_recommendation(
        session, hotel_id, stay_date
    )
    if recommendation is None:
        raise not_found("Hotel", hotel_id)
    return recommendation
