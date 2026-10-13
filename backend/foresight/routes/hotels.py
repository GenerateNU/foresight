from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from foresight.routes.common import PageDep, SessionDep, not_found, paginate
from foresight.schemas.common import PageResponse
from foresight.schemas.hotel import (
    DailyPerformanceResponse,
    HotelRequest,
    HotelResponse,
    RoomTypeRequest,
    RoomTypeResponse,
)
from foresight.schemas.recommendation import RecommendationResponse
from foresight.services import hotel as hotel_service
from foresight.services import recommendation as recommendation_service

router = APIRouter(tags=["hotels"])


@router.post(
    "/hotels", response_model=HotelResponse, status_code=status.HTTP_201_CREATED
)
async def create_hotel(data: HotelRequest, session: SessionDep) -> HotelResponse:
    hotel = await hotel_service.create_hotel(session, data)
    return HotelResponse.model_validate(hotel)


@router.get("/hotels", response_model=PageResponse[HotelResponse])
async def list_hotels(
    session: SessionDep, page: PageDep
) -> PageResponse[HotelResponse]:
    hotels, total = await hotel_service.list_hotels(
        session, limit=page.limit, offset=page.offset
    )
    return paginate(HotelResponse, hotels, total, page)


@router.get("/hotels/{hotel_id}", response_model=HotelResponse)
async def get_hotel(hotel_id: int, session: SessionDep) -> HotelResponse:
    hotel = await hotel_service.get_hotel(session, hotel_id)
    if hotel is None:
        raise not_found("Hotel", hotel_id)
    return HotelResponse.model_validate(hotel)


@router.post(
    "/room-types", response_model=RoomTypeResponse, status_code=status.HTTP_201_CREATED
)
async def create_room_type(
    data: RoomTypeRequest, session: SessionDep
) -> RoomTypeResponse:
    room_type = await hotel_service.create_room_type(session, data)
    return RoomTypeResponse.model_validate(room_type)


@router.get("/room-types/{room_type_id}", response_model=RoomTypeResponse)
async def get_room_type(room_type_id: int, session: SessionDep) -> RoomTypeResponse:
    room_type = await hotel_service.get_room_type(session, room_type_id)
    if room_type is None:
        raise not_found("Room type", room_type_id)
    return RoomTypeResponse.model_validate(room_type)


@router.get(
    "/hotels/{hotel_id}/room-types", response_model=PageResponse[RoomTypeResponse]
)
async def list_room_types(
    hotel_id: int, session: SessionDep, page: PageDep
) -> PageResponse[RoomTypeResponse]:
    room_types, total = await hotel_service.list_room_types(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    return paginate(RoomTypeResponse, room_types, total, page)


@router.get(
    "/hotels/{hotel_id}/performance",
    response_model=PageResponse[DailyPerformanceResponse],
)
async def list_performance(
    hotel_id: int,
    session: SessionDep,
    page: PageDep,
    start: date | None = None,
    end: date | None = None,
    room_type_id: int | None = None,
) -> PageResponse[DailyPerformanceResponse]:
    """Nightly performance across the hotel's room types; `start`/`end` inclusive."""
    nights, total = await hotel_service.list_performance(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_id=room_type_id,
        limit=page.limit,
        offset=page.offset,
    )
    return paginate(DailyPerformanceResponse, nights, total, page)


@router.get("/hotels/{hotel_id}/recommendations", response_model=RecommendationResponse)
async def get_recommendation(
    hotel_id: int,
    session: SessionDep,
    # Named `stay_date` in code because `date` is the type; the query key stays `date`.
    stay_date: Annotated[date, Query(alias="date")],
) -> RecommendationResponse:
    """Placeholder rate for one night, in the final response shape."""
    recommendation = await recommendation_service.get_recommendation(
        session, hotel_id, stay_date
    )
    # ResponseSchema reads attributes, so the nested dataclasses map directly.
    return RecommendationResponse.model_validate(recommendation)
