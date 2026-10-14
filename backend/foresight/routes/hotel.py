"""Hotels, their room types, nightly performance, and recommendations."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import Field, computed_field, field_validator

from foresight.routes.city import CityResponse
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    RequestSchema,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services.domain import hotel as hotel_service
from foresight.services.domain import recommendation as recommendation_service

router = APIRouter(tags=["hotels"])


# --- schemas ----------------------------------------------------------------


class HotelRequest(RequestSchema):
    name: str = Field(max_length=200)
    city_id: int = Field(description="The market the hotel sits in; see /cities")
    total_rooms: int = Field(gt=0)
    latitude: float | None = Field(
        default=None, ge=-90, le=90, description="The hotel itself, not the city"
    )
    longitude: float | None = Field(default=None, ge=-180, le=180)


class HotelUpdateRequest(RequestSchema):
    """Only the fields sent are changed; send null to clear an optional one."""

    name: str | None = Field(default=None, max_length=200)
    city_id: int | None = None
    total_rooms: int | None = Field(default=None, gt=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("name", "city_id", "total_rooms")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Required columns: omitting them leaves them alone, null can't clear them.
        if value is None:
            raise ValueError("cannot be null")
        return value


class HotelResponse(ResponseSchema):
    id: int
    name: str
    city: CityResponse
    total_rooms: int
    latitude: float | None
    longitude: float | None


class RoomTypeRequest(RequestSchema):
    name: str = Field(max_length=120, description='e.g. "Deluxe King"')
    room_count: int = Field(gt=0, description="Physical rooms of this type")
    base_rate: Decimal = Field(gt=0, description="The normal nightly price")


class RoomTypeResponse(ResponseSchema):
    id: int
    hotel_id: int
    name: str
    room_count: int
    base_rate: Decimal


class DailyPerformanceResponse(ResponseSchema):
    """Adds the three standard hotel metrics, calculated rather than stored."""

    id: int
    room_type_id: int
    stay_date: date
    rate: Decimal | None = Field(description="Listed price; null if unsold")
    rooms_available: int
    rooms_sold: int
    room_revenue: Decimal

    @computed_field
    @property
    def occupancy(self) -> float | None:
        """Share of rooms sold, 0-1."""
        if not self.rooms_available:
            return None
        return round(self.rooms_sold / self.rooms_available, 4)

    @computed_field
    @property
    def adr(self) -> Decimal | None:
        """Average Daily Rate: revenue per room sold."""
        if not self.rooms_sold:
            return None
        return round(self.room_revenue / self.rooms_sold, 2)

    @computed_field
    @property
    def revpar(self) -> Decimal | None:
        """Revenue Per Available Room: revenue per room we had to sell."""
        if not self.rooms_available:
            return None
        return round(self.room_revenue / self.rooms_available, 2)


class FactorResponse(ResponseSchema):
    """One signal's pull on the recommended rate."""

    signal: str = Field(description='e.g. "events", "weather", "flights"')
    direction: Literal["up", "down", "neutral"]
    detail: str


class ExplanationResponse(ResponseSchema):
    summary: str
    factors: list[FactorResponse]


class ConfidenceIntervalResponse(ResponseSchema):
    lower: Decimal
    upper: Decimal
    level: float = Field(description="Coverage, e.g. 0.95")


class RecommendationResponse(ResponseSchema):
    hotel_id: int
    stay_date: date
    recommended_rate: Decimal
    currency: str
    explanation: ExplanationResponse
    confidence_interval: ConfidenceIntervalResponse
    model_version: str
    is_placeholder: bool = Field(description="True until the pricing model is wired in")


# --- endpoints --------------------------------------------------------------


@router.post(
    "/hotels", response_model=HotelResponse, status_code=status.HTTP_201_CREATED
)
async def create_hotel(data: HotelRequest, session: SessionDep) -> HotelResponse:
    """Add a hotel to a city. Names are unique per city."""
    hotel = await hotel_service.create_hotel(session, **data.model_dump())
    return HotelResponse.model_validate(hotel)


@router.get("/hotels", response_model=list[HotelResponse])
async def list_hotels(session: SessionDep) -> list[HotelResponse]:
    """Every hotel, oldest first."""
    hotels = await hotel_service.list_hotels(session)
    return [HotelResponse.model_validate(hotel) for hotel in hotels]


@router.get("/hotels/{hotel_id}", response_model=HotelResponse)
async def get_hotel(hotel_id: int, session: SessionDep) -> HotelResponse:
    """One hotel, with its city."""
    return HotelResponse.model_validate(
        await hotel_service.get_hotel(session, hotel_id)
    )


@router.patch("/hotels/{hotel_id}", response_model=HotelResponse)
async def update_hotel(
    hotel_id: int, data: HotelUpdateRequest, session: SessionDep
) -> HotelResponse:
    """Change the fields sent; omitted fields are left alone."""
    hotel = await hotel_service.update_hotel(
        session, hotel_id, data.model_dump(exclude_unset=True)
    )
    return HotelResponse.model_validate(hotel)


@router.post(
    "/hotels/{hotel_id}/room-types",
    response_model=RoomTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room_type(
    hotel_id: int, data: RoomTypeRequest, session: SessionDep
) -> RoomTypeResponse:
    """Add a room type to the hotel. Names are unique per hotel."""
    room_type = await hotel_service.create_room_type(
        session, hotel_id, **data.model_dump()
    )
    return RoomTypeResponse.model_validate(room_type)


@router.get("/hotels/{hotel_id}/room-types", response_model=list[RoomTypeResponse])
async def list_room_types(hotel_id: int, session: SessionDep) -> list[RoomTypeResponse]:
    """The hotel's room types."""
    room_types = await hotel_service.list_room_types(session, hotel_id)
    return [RoomTypeResponse.model_validate(r) for r in room_types]


@router.get("/room-types/{room_type_id}", response_model=RoomTypeResponse)
async def get_room_type(room_type_id: int, session: SessionDep) -> RoomTypeResponse:
    """One room type."""
    return RoomTypeResponse.model_validate(
        await hotel_service.get_room_type(session, room_type_id)
    )


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
    return RecommendationResponse.model_validate(recommendation)
