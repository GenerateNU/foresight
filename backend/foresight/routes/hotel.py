"""Hotels, their room types, nightly performance, the events on each night, and
recommendations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status
from pydantic import Field, computed_field, field_validator

from foresight.database.enums import EventCategory
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
from foresight.services.domain import night as night_service
from foresight.services.domain import recommendation as recommendation_service

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


class RoomTypeRequest(RequestSchema):
    name: str = Field(
        max_length=120,
        description="The room type's name; unique within the hotel",
        examples=["Example Room"],
    )
    room_count: int = Field(
        gt=0, description="Physical rooms of this type", examples=[50]
    )
    base_rate: Decimal = Field(
        gt=0,
        description="The standard nightly price (rack rate), in EUR",
        examples=["100.00"],
    )


class RoomTypeResponse(ResponseSchema):
    id: int = Field(description="The room type's id")
    hotel_id: int = Field(description="The hotel it belongs to")
    name: str = Field(description="The room type's name")
    room_count: int = Field(description="Physical rooms of this type")
    base_rate: Decimal = Field(description="The standard nightly price, in EUR")


class DailyPerformanceResponse(ResponseSchema):
    """Adds the three standard hotel metrics, calculated rather than stored."""

    id: int = Field(description="The night's row id")
    room_type_id: int = Field(description="The room type sold")
    stay_date: date = Field(description="The night, local to the hotel's city")
    rate: Decimal | None = Field(
        description="Average rate paid that night, in EUR; null if unsold"
    )
    rooms_available: int = Field(description="Rooms of this type for sale")
    rooms_sold: int = Field(description="Rooms of this type sold")
    room_revenue: Decimal = Field(description="Revenue from these rooms, in EUR")

    @computed_field
    @property
    def occupancy(self) -> float | None:
        """Share of rooms sold, 0-1; null if none were available."""
        if not self.rooms_available:
            return None
        return round(self.rooms_sold / self.rooms_available, 4)

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
        """Revenue Per Available Room, in EUR; null if none were available."""
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


class RecommendationResponse(ResponseSchema):
    hotel_id: int = Field(description="The hotel priced")
    stay_date: date = Field(description="The night priced, local to the city")
    room_type: str = Field(description="The room type priced")
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
    is_placeholder: bool = Field(description="Always false; kept for older clients")


class SnapshotResponse(ResponseSchema):
    """One saved recommendation: what the model said for a night, and when."""

    id: int = Field(description="The snapshot's id")
    room_type_id: int = Field(description="The room type priced")
    stay_date: date = Field(description="The night priced, local to the city")
    rate: Decimal = Field(description="The recommended rate, in EUR")
    interval_low: Decimal = Field(description="Low end of the 80% range, in EUR")
    interval_high: Decimal = Field(description="High end of the 80% range, in EUR")
    uncertainty: Decimal = Field(
        description="How much the model's sub-models disagree, in EUR. High "
        "means an unusual night: review the rate"
    )
    model_id: int = Field(description="The model version that priced it")
    model_version: str = Field(description="Algorithm and version", examples=["ebm-v1"])
    factors: dict[str, Any] = Field(
        description="Summary, baseline and each factor's pull on the rate; "
        "amounts in EUR, as strings"
    )
    created_at: datetime = Field(description="When the model produced this rate")


class NightSnapshotResponse(ResponseSchema):
    """A night's latest recommendation and how it moved since the one before."""

    latest: SnapshotResponse = Field(description="The newest snapshot for the night")
    previous: SnapshotResponse | None = Field(
        description="The snapshot before it; null if the night has only one"
    )

    @computed_field
    @property
    def change(self) -> Decimal | None:
        """Latest rate minus previous rate, in EUR; null without a previous one."""
        if self.previous is None:
            return None
        return self.latest.rate - self.previous.rate


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


class NightResponse(ResponseSchema):
    hotel_id: int = Field(description="The hotel")
    stay_date: date = Field(description="The night, local to the city")
    events: list[NightEventResponse] = Field(
        description="Events affecting the night, largest first: expected "
        "attendance, then local rank, unknown values last. Withdrawn events "
        "are left out"
    )


class NightRateResponse(ResponseSchema):
    stay_date: date = Field(description="The night priced, local to the city")
    recommended_rate: Decimal = Field(description="The rate to list, in `currency`")
    currency: str = Field(description="ISO-4217 currency code", examples=["EUR"])
    event_names: list[str] = Field(
        description="Names of the events affecting the night, largest first"
    )


HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]
RoomTypeId = Annotated[int, Path(description="The room type's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


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


@router.get("/hotels/{hotel_id}/events/{stay_date}", response_model=NightResponse)
async def get_events(
    hotel_id: HotelId,
    session: SessionDep,
    stay_date: Annotated[
        date,
        Path(description="The night. YYYY-MM-DD", examples=["2025-01-01"]),
    ],
) -> NightResponse:
    """The events affecting one night, with full details. A multi-day event
    shows on each of its nights as day N of M."""
    night = await night_service.get_events(session, hotel_id, stay_date)
    return NightResponse.model_validate(night)


@router.get("/hotels/{hotel_id}/recommendations", response_model=RecommendationResponse)
async def get_recommendation(
    hotel_id: HotelId,
    session: SessionDep,
    # Named `stay_date` in code because `date` is the type; the query key stays `date`.
    stay_date: Annotated[
        date,
        Query(
            alias="date",
            description="The night to price. YYYY-MM-DD",
            examples=["2025-01-01"],
        ),
    ],
    room_type_id: Annotated[
        int | None,
        Query(
            description="The room type to price; omit for the hotel's first",
            examples=[1],
        ),
    ] = None,
) -> RecommendationResponse:
    """The active model's rate for one night, with its explanation.

    Uses only ingested data: recorded weather, else the forecast, else the
    typical weather for that week. 404 if the hotel has no active model.
    """
    recommendation = await recommendation_service.get_recommendation(
        session, hotel_id, stay_date, room_type_id=room_type_id
    )
    return RecommendationResponse.model_validate(recommendation)


@router.get(
    "/hotels/{hotel_id}/recommendations/range",
    response_model=list[NightRateResponse],
)
async def get_recommendation_range(
    hotel_id: HotelId,
    session: SessionDep,
    start: Annotated[
        date,
        Query(
            description="First night, inclusive. YYYY-MM-DD", examples=["2025-01-01"]
        ),
    ],
    end: Annotated[
        date,
        Query(description="Last night, inclusive. YYYY-MM-DD", examples=["2025-01-31"]),
    ],
    room_type_id: Annotated[
        int | None,
        Query(
            description="The room type to price; omit for the hotel's first",
            examples=[1],
        ),
    ] = None,
) -> list[NightRateResponse]:
    """The recommended rate for every night in the range, with the names of the
    events affecting each. Limited to 62 nights; 404 if the hotel has no active
    model."""
    rates = await night_service.recommendation_range(
        session, hotel_id, start=start, end=end, room_type_id=room_type_id
    )
    return [NightRateResponse.model_validate(rate) for rate in rates]


@router.get(
    "/hotels/{hotel_id}/recommendations/snapshot",
    response_model=NightSnapshotResponse,
)
async def get_recommendation_snapshot(
    hotel_id: HotelId,
    session: SessionDep,
    # Named `stay_date` in code because `date` is the type; the query key stays `date`.
    stay_date: Annotated[
        date,
        Query(
            alias="date",
            description="The night. YYYY-MM-DD",
            examples=["2025-01-01"],
        ),
    ],
    room_type_id: Annotated[
        int | None,
        Query(
            description="The room type; omit for the hotel's first",
            examples=[1],
        ),
    ] = None,
) -> NightSnapshotResponse:
    """The night's latest saved rate, the one before it, and the change.

    A future night with no snapshot is priced and saved now. 404 for a past
    night with none, since history isn't created after the fact.
    """
    latest, previous = await recommendation_service.get_snapshot(
        session, hotel_id, stay_date, room_type_id=room_type_id
    )
    return NightSnapshotResponse(
        latest=SnapshotResponse.model_validate(latest),
        previous=SnapshotResponse.model_validate(previous) if previous else None,
    )


@router.post(
    "/hotels/{hotel_id}/recommendations/snapshots",
    response_model=list[SnapshotResponse],
)
async def snapshot_recommendations(
    hotel_id: HotelId,
    session: SessionDep,
    days: Annotated[
        int,
        Query(ge=1, le=90, description="How many nights to price, starting today"),
    ] = 30,
    room_type_id: Annotated[
        int | None,
        Query(
            description="The room type; omit for every room type the active "
            "model was trained on",
            examples=[1],
        ),
    ] = None,
) -> list[SnapshotResponse]:
    """Price each night from today and save the rates that changed.

    Returns only the snapshots saved by this call; a night whose rate didn't
    change since its latest snapshot is skipped.
    """
    saved = await recommendation_service.snapshot_recommendations(
        session, hotel_id, days=days, room_type_id=room_type_id
    )
    return [SnapshotResponse.model_validate(s) for s in saved]
