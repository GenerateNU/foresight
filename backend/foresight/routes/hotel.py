"""Hotels, their room types, nightly performance, and recommendations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import Field, computed_field, field_validator

from foresight.database.enums import EventCategory
from foresight.routes.access import CurrentUserDep, HotelId, RoomTypeId
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
from foresight.services.domain import user as user_service
from foresight.services.errors import InvalidRequestError

router = APIRouter(tags=["Hotels"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

# Field settings shared by the create and update bodies.
_HOTEL_NAME: dict[str, Any] = {
    "max_length": 200,
    "description": "The hotel's name; unique within its city",
    "examples": ["Example Hotel"],
}
_CITY_ID: dict[str, Any] = {
    "description": "The city the hotel sits in; see /cities",
    "examples": [1],
}
_TOTAL_ROOMS: dict[str, Any] = {
    "gt": 0,
    "description": "Rooms across every room type",
    "examples": [100],
}
_LATITUDE: dict[str, Any] = {
    "ge": -90,
    "le": 90,
    "description": "The hotel itself, not the city, in degrees",
    "examples": [12.34],
}
_LONGITUDE: dict[str, Any] = {
    "ge": -180,
    "le": 180,
    "description": "The hotel itself, not the city, in degrees",
    "examples": [-56.78],
}


class HotelRequest(RequestSchema):
    name: str = Field(**_HOTEL_NAME)
    city_id: int = Field(**_CITY_ID)
    total_rooms: int = Field(**_TOTAL_ROOMS)
    latitude: float | None = Field(default=None, **_LATITUDE)
    longitude: float | None = Field(default=None, **_LONGITUDE)


class HotelUpdateRequest(RequestSchema):
    """Only the fields sent are changed; send null to clear an optional one."""

    name: str | None = Field(default=None, **_HOTEL_NAME)
    city_id: int | None = Field(default=None, **_CITY_ID)
    total_rooms: int | None = Field(default=None, **_TOTAL_ROOMS)
    latitude: float | None = Field(default=None, **_LATITUDE)
    longitude: float | None = Field(default=None, **_LONGITUDE)

    @field_validator("name", "city_id", "total_rooms")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Required columns: omitting them leaves them alone, null can't clear them.
        if value is None:
            raise ValueError("cannot be null")
        return value


class HotelResponse(ResponseSchema):
    id: int = Field(description="The hotel's id")
    name: str = Field(description="The hotel's name")
    city: CityResponse = Field(description="The city the hotel sits in")
    total_rooms: int = Field(description="Rooms across every room type")
    latitude: float | None = Field(description="The hotel itself, in degrees")
    longitude: float | None = Field(description="The hotel itself, in degrees")


class LinkUserRequest(RequestSchema):
    email: str = Field(
        max_length=320,
        description="The Google email of someone who has signed in at least once",
        examples=["colleague@example.com"],
    )


class RoomTypeRequest(RequestSchema):
    name: str = Field(
        max_length=120,
        description="The room type's name; unique within the hotel",
        examples=["Example Room"],
    )
    room_count: int = Field(
        gt=0, description="Physical rooms of this type", examples=[50]
    )


class RoomTypeResponse(ResponseSchema):
    id: int = Field(description="The room type's id")
    hotel_id: int = Field(description="The hotel it belongs to")
    name: str = Field(description="The room type's name")
    room_count: int = Field(description="Physical rooms of this type")


class DailyPerformanceResponse(ResponseSchema):
    """Adds the three standard hotel metrics, calculated rather than stored."""

    id: int = Field(description="The night's row id")
    room_type_id: int = Field(description="The room type sold")
    stay_date: date = Field(description="The night, local to the hotel's city")
    rate: Decimal | None = Field(
        description="Average rate paid that night, in EUR; null if unsold"
    )
    rooms_available: int = Field(
        description="Rooms of this type in stock, including any out of service"
    )
    rooms_sold: int = Field(description="Rooms of this type sold")
    room_revenue: Decimal = Field(description="Revenue from these rooms, in EUR")
    rooms_blocked: int | None = Field(
        description="Rooms sold through group blocks; null if not imported"
    )
    rooms_out_of_service: int | None = Field(
        description="Rooms that couldn't be sold that night; null if not imported"
    )
    waitlist: int | None = Field(
        description="Guests on the waitlist; null if not imported"
    )

    @computed_field
    @property
    def sellable_rooms(self) -> int:
        """Rooms that could be sold: in stock minus out of service."""
        return self.rooms_available - (self.rooms_out_of_service or 0)

    @computed_field
    @property
    def occupancy(self) -> float | None:
        """Share of sellable rooms sold, 0-1; null if none could be sold.

        Guestline's Occ% counts out-of-service rooms as unsold, so a sold-out
        night can show 99% there and 100% here.
        """
        if self.sellable_rooms <= 0:
            return None
        # Exports can show more rooms sold than sellable (1 of 1,025 real nights).
        return round(min(self.rooms_sold / self.sellable_rooms, 1), 4)

    @computed_field
    @property
    def adr(self) -> Decimal | None:
        """Average Daily Rate: revenue per room sold, in EUR; null if none sold."""
        if not self.rooms_sold:
            return None
        return round(self.room_revenue / self.rooms_sold, 2)

    @computed_field
    @property
    def revpar(self) -> Decimal | None:
        """Revenue per room in stock, in EUR; null if none were in stock."""
        if not self.rooms_available:
            return None
        return round(self.room_revenue / self.rooms_available, 2)


class FactorResponse(ResponseSchema):
    """One term's pull on the recommended rate."""

    detail: str = Field(description="The factor, in words", examples=["Saturday"])
    amount: Decimal = Field(
        description="Contribution in EUR; baseline plus every amount is the "
        "recommended rate"
    )


class ExplanationResponse(ResponseSchema):
    summary: str = Field(description="The rate and its biggest factor, in words")
    baseline: Decimal = Field(description="The model's rate before any factor, EUR")
    factors: list[FactorResponse] = Field(description="Largest first")


class ConfidenceIntervalResponse(ResponseSchema):
    lower: Decimal = Field(description="Low end of the range, in EUR")
    upper: Decimal = Field(description="High end of the range, in EUR")
    level: float = Field(
        description="Share of nights expected to fall inside the range",
        examples=[0.8],
    )


class NightEventResponse(ResponseSchema):
    """An event as it falls on one night."""

    event_id: int = Field(description="The event's id")
    title: str = Field(description="The event's name")
    venue: str | None = Field(description="Where it's held; null if unknown")
    category: EventCategory = Field(description="What kind of event it is")
    expected_attendance: int | None = Field(
        description="Predicted people; null if unknown"
    )
    day_number: int = Field(
        description="Which day of the event this night is, counting from 1",
        examples=[2],
    )
    day_count: int = Field(
        description="Days the event runs, so 'day 2 of 3' is 2 and 3; 1 for a "
        "single-day event",
        examples=[3],
    )


class RecommendationResponse(ResponseSchema):
    hotel_id: int = Field(description="The hotel priced")
    stay_date: date = Field(description="The night priced, local to the city")
    room_type: str = Field(description="The room type priced")
    room_type_id: int = Field(description="The room type's id")
    recommended_rate: Decimal = Field(description="The rate to list, in `currency`")
    currency: str = Field(description="ISO-4217 currency code", examples=["EUR"])
    explanation: ExplanationResponse = Field(description="Why the rate is what it is")
    confidence_interval: ConfidenceIntervalResponse = Field(
        description="The range the rate is likely to fall in"
    )
    uncertainty: Decimal = Field(
        description="How much the model's sub-models disagree, in EUR. High "
        "means an unusual night: review the rate"
    )
    model_id: int = Field(description="The model version that priced it")
    model_version: str = Field(description="Algorithm and version", examples=["ebm-v1"])
    events: list[NightEventResponse] = Field(
        description="Events on the night that the model counts, largest first: "
        "expected attendance, then local rank. Withdrawn events are left out"
    )
    events_source: str | None = Field(
        description="Whether an events backfill covered the night: fetched, or "
        "missing, meaning its event features are unknown rather than quiet; "
        "null on snapshots older than this field",
        examples=["fetched"],
    )
    snapshot_id: int | None = Field(
        description="The snapshot this rate is stored as; null for a past night "
        "priced now, since past nights aren't saved after the fact"
    )
    priced_at: datetime = Field(
        description="When the model produced this rate, UTC. Older than the "
        "request when the night's inputs haven't changed since"
    )


RecommendRoomType = Annotated[
    int | None,
    Query(
        description="The room type to price; omit for the hotel's first",
        examples=[1],
    ),
]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post(
    "/hotels", response_model=HotelResponse, status_code=status.HTTP_201_CREATED
)
async def create_hotel(
    data: HotelRequest, user: CurrentUserDep, session: SessionDep
) -> HotelResponse:
    """Add a hotel to a city, and link yourself to it. Names are unique per city."""
    hotel = await hotel_service.create_hotel_for_user(
        session, user, **data.model_dump()
    )
    return HotelResponse.model_validate(hotel)


@router.get("/hotels", response_model=list[HotelResponse])
async def list_hotels(user: CurrentUserDep, session: SessionDep) -> list[HotelResponse]:
    """The hotels you're linked to, oldest first; empty if you have none."""
    hotels = await hotel_service.list_hotels_for_user(session, user.id)
    return [HotelResponse.model_validate(hotel) for hotel in hotels]


@router.get("/hotels/{hotel_id}", response_model=HotelResponse)
async def get_hotel(hotel_id: HotelId, session: SessionDep) -> HotelResponse:
    """One hotel, with its city."""
    return HotelResponse.model_validate(
        await hotel_service.get_hotel(session, hotel_id)
    )


@router.patch("/hotels/{hotel_id}", response_model=HotelResponse)
async def update_hotel(
    hotel_id: HotelId, data: HotelUpdateRequest, session: SessionDep
) -> HotelResponse:
    """Change the fields sent; omitted fields are left alone."""
    hotel = await hotel_service.update_hotel(
        session, hotel_id, data.model_dump(exclude_unset=True)
    )
    return HotelResponse.model_validate(hotel)


@router.post("/hotels/{hotel_id}/users", status_code=status.HTTP_204_NO_CONTENT)
async def link_user(
    hotel_id: HotelId, data: LinkUserRequest, session: SessionDep
) -> None:
    """Give a colleague access to this hotel, by the email of their Google
    account. They must have signed in once. Linking twice changes nothing."""
    await user_service.link_user_by_email(session, hotel_id=hotel_id, email=data.email)


@router.post(
    "/hotels/{hotel_id}/room-types",
    response_model=RoomTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room_type(
    hotel_id: HotelId, data: RoomTypeRequest, session: SessionDep
) -> RoomTypeResponse:
    """Add a room type to the hotel. Names are unique per hotel."""
    room_type = await hotel_service.create_room_type(
        session, hotel_id, **data.model_dump()
    )
    return RoomTypeResponse.model_validate(room_type)


@router.get("/hotels/{hotel_id}/room-types", response_model=list[RoomTypeResponse])
async def list_room_types(
    hotel_id: HotelId, session: SessionDep
) -> list[RoomTypeResponse]:
    """The hotel's room types."""
    room_types = await hotel_service.list_room_types(session, hotel_id)
    return [RoomTypeResponse.model_validate(r) for r in room_types]


@router.get("/room-types/{room_type_id}", response_model=RoomTypeResponse)
async def get_room_type(
    room_type_id: RoomTypeId, session: SessionDep
) -> RoomTypeResponse:
    """One room type."""
    return RoomTypeResponse.model_validate(
        await hotel_service.get_room_type(session, room_type_id)
    )


@router.get(
    "/hotels/{hotel_id}/performance",
    response_model=PageResponse[DailyPerformanceResponse],
)
async def list_performance(
    hotel_id: HotelId,
    session: SessionDep,
    page: PageDep,
    start: Annotated[
        date | None,
        Query(
            description="First night, inclusive. YYYY-MM-DD",
            examples=["2025-01-01"],
        ),
    ] = None,
    end: Annotated[
        date | None,
        Query(
            description="Last night, inclusive. YYYY-MM-DD",
            examples=["2025-12-31"],
        ),
    ] = None,
    room_type_id: Annotated[
        int | None,
        Query(description="Only this room type; omit for all", examples=[1]),
    ] = None,
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


@router.get(
    "/hotels/{hotel_id}/recommendations",
    response_model=list[RecommendationResponse],
)
async def get_recommendations(
    hotel_id: HotelId,
    session: SessionDep,
    # Named `stay_date` in code because `date` is the type; the query key stays `date`.
    stay_date: Annotated[
        date | None,
        Query(
            alias="date",
            description="One night. YYYY-MM-DD. Send this, or `start` (and `end`)",
            examples=["2025-01-01"],
        ),
    ] = None,
    start: Annotated[
        date | None,
        Query(
            description="First night, inclusive. YYYY-MM-DD", examples=["2025-01-01"]
        ),
    ] = None,
    end: Annotated[
        date | None,
        Query(
            description="Last night, inclusive; omit for `start` alone. YYYY-MM-DD",
            examples=["2025-01-31"],
        ),
    ] = None,
    room_type_id: RecommendRoomType = None,
) -> list[RecommendationResponse]:
    """The active model's rate for each night, oldest first, with its
    explanation and events. At most 90 nights.

    Each night from today on is stored as a snapshot. A night whose inputs
    (model, events) haven't changed since its latest snapshot returns
    that snapshot without running the model; one whose inputs changed is priced
    again and stored. Past nights are never stored after the fact: one with a
    snapshot returns it as it was, one without is priced and returned unsaved.
    404 if the hotel has no active model.
    """
    if stay_date is not None and (start is not None or end is not None):
        raise InvalidRequestError("send `date`, or `start` and `end`, not both")
    first = stay_date or start
    if first is None:
        raise InvalidRequestError("send `date`, or `start` and `end`")
    recommendations = await recommendation_service.get_recommendations(
        session, hotel_id, start=first, end=end or first, room_type_id=room_type_id
    )
    return [RecommendationResponse.model_validate(r) for r in recommendations]
