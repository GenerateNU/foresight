from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import Field, field_validator

from foresight.database.enums import EventCategory
from foresight.routes.access import CurrentUserDep, HotelId
from foresight.routes.city import CityResponse
from foresight.routes.helpers import (
    RequestSchema,
    ResponseSchema,
    SessionDep,
)
from foresight.services.errors import InvalidRequestError
from foresight.services.hotels import hotel as hotel_service
from foresight.services.recommendations import recommendation as recommendation_service
from foresight.services.users import user as user_service

router = APIRouter(tags=["Hotels"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

_HOTEL_NAME: dict[str, Any] = {
    "max_length": 200,
    "description": "The hotel's name; unique within its city",
    "examples": ["Example Hotel"],
}
_CITY_ID: dict[str, Any] = {
    "description": "The city the hotel sits in; see /cities",
    "examples": [1],
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
    """A new hotel."""

    name: str = Field(**_HOTEL_NAME)
    city_id: int = Field(**_CITY_ID)
    latitude: float | None = Field(default=None, **_LATITUDE)
    longitude: float | None = Field(default=None, **_LONGITUDE)


class HotelUpdateRequest(RequestSchema):
    """Only the fields sent are changed; send null to clear an optional one."""

    name: str | None = Field(default=None, **_HOTEL_NAME)
    city_id: int | None = Field(default=None, **_CITY_ID)
    latitude: float | None = Field(default=None, **_LATITUDE)
    longitude: float | None = Field(default=None, **_LONGITUDE)

    @field_validator("name", "city_id")
    @classmethod
    def _not_null(cls, value: object) -> object:
        """Rejects null for a required column; leaving it out leaves it alone.

        Args:
            value (object): The value sent.

        Returns:
            object: The value.

        Raises:
            ValueError: It's null.
        """
        if value is None:
            raise ValueError("cannot be null")
        return value


class HotelResponse(ResponseSchema):
    """A hotel, with its city."""

    id: int = Field(description="The hotel's id")
    name: str = Field(description="The hotel's name")
    city: CityResponse = Field(description="The city the hotel sits in")
    latitude: float | None = Field(description="The hotel itself, in degrees")
    longitude: float | None = Field(description="The hotel itself, in degrees")


class LinkUserRequest(RequestSchema):
    """The colleague to give access to."""

    email: str = Field(
        max_length=320,
        description="The Google email of someone who has signed in at least once",
        examples=["colleague@example.com"],
    )


class FactorResponse(ResponseSchema):
    """One term's pull on the recommended rate."""

    detail: str = Field(description="The factor, in words", examples=["Saturday"])
    amount: Decimal = Field(
        description="Contribution in EUR; baseline plus every amount is the "
        "recommended rate"
    )


class ExplanationResponse(ResponseSchema):
    """Why a night's rate is what it is."""

    summary: str = Field(description="The rate and its biggest factor, in words")
    baseline: Decimal = Field(description="The model's rate before any factor, EUR")
    factors: list[FactorResponse] = Field(description="Largest first")


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
    """One night's recommended rate, why, and what it was priced from."""

    hotel_id: int = Field(description="The hotel priced")
    stay_date: date = Field(description="The night priced, local to the city")
    room_type: str = Field(description="The room type priced")
    room_type_id: int = Field(description="The room type's id")
    lead_days: int | None = Field(
        description="Days from today to the night (0 for today and past "
        "nights). The rate is what the night would sell for if booked today. "
        "Null on snapshots from versions that didn't read it"
    )
    recommended_rate: Decimal = Field(
        description="The rate to list, in EUR, before VAT"
    )
    explanation: ExplanationResponse = Field(description="Why the rate is what it is")
    model_id: int = Field(description="The model version that priced it")
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
    manager_rate: Decimal | None = Field(
        default=None,
        description="The rate the manager set for the night, in EUR, "
        "before VAT like `recommended_rate`; null if they haven't. Shown "
        "alongside it so a calendar needs one call",
        examples=["210.00"],
    )
    snapshot_id: int | None = Field(
        description="The snapshot this rate is stored as; null for a past night "
        "priced now, since past nights aren't saved after the fact"
    )
    priced_at: datetime = Field(
        description="When the model produced this rate, UTC. Older than the "
        "request when the night's model and inputs haven't changed since"
    )


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post(
    "/hotels", response_model=HotelResponse, status_code=status.HTTP_201_CREATED
)
async def create_hotel(
    data: HotelRequest, user: CurrentUserDep, session: SessionDep
) -> HotelResponse:
    """Add a hotel to a city, and link yourself to it. Names are unique per city.

    \f
    Args:
        data (HotelRequest): The hotel.
        user (CurrentUserDep): The creator.
        session (SessionDep): The database session.

    Returns:
        HotelResponse: The new hotel.

    Raises:
        NotFoundError: The city doesn't exist.
        ConflictError: The city already has a hotel with this name.
    """
    hotel = await hotel_service.create_hotel_for_user(
        session, user, **data.model_dump()
    )
    return HotelResponse.model_validate(hotel)


@router.get("/hotels", response_model=list[HotelResponse])
async def list_hotels(user: CurrentUserDep, session: SessionDep) -> list[HotelResponse]:
    """The hotels you're linked to, oldest first; empty if you have none.

    \f
    Args:
        user (CurrentUserDep): The signed-in user.
        session (SessionDep): The database session.

    Returns:
        list[HotelResponse]: The hotels.
    """
    hotels = await hotel_service.list_hotels_for_user(session, user.id)
    return [HotelResponse.model_validate(hotel) for hotel in hotels]


@router.get("/hotels/{hotel_id}", response_model=HotelResponse)
async def get_hotel(hotel_id: HotelId, session: SessionDep) -> HotelResponse:
    """One hotel, with its city.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        session (SessionDep): The database session.

    Returns:
        HotelResponse: The hotel.
    """
    return HotelResponse.model_validate(
        await hotel_service.get_hotel(session, hotel_id)
    )


@router.patch("/hotels/{hotel_id}", response_model=HotelResponse)
async def update_hotel(
    hotel_id: HotelId, data: HotelUpdateRequest, session: SessionDep
) -> HotelResponse:
    """Change the fields sent; omitted fields are left alone.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        data (HotelUpdateRequest): The changes.
        session (SessionDep): The database session.

    Returns:
        HotelResponse: The updated hotel.

    Raises:
        NotFoundError: The new city doesn't exist.
        ConflictError: The new name and city match another hotel.
    """
    hotel = await hotel_service.update_hotel(
        session, hotel_id, data.model_dump(exclude_unset=True)
    )
    return HotelResponse.model_validate(hotel)


@router.post("/hotels/{hotel_id}/users", status_code=status.HTTP_204_NO_CONTENT)
async def link_user(
    hotel_id: HotelId, data: LinkUserRequest, session: SessionDep
) -> None:
    """Give a colleague access to this hotel, by their Google account's email.

    They must have signed in once. Linking twice changes nothing.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        data (LinkUserRequest): Their email.
        session (SessionDep): The database session.

    Raises:
        NotFoundError: Nobody with this email has signed in.
        ConflictError: Several users share the email.
    """
    await user_service.link_user_by_email(session, hotel_id=hotel_id, email=data.email)


@router.get(
    "/hotels/{hotel_id}/recommendations",
    response_model=list[RecommendationResponse],
)
async def get_recommendations(
    hotel_id: HotelId,
    session: SessionDep,
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
) -> list[RecommendationResponse]:
    """The active model's rate for each night, with its explanation and events.

    Oldest first; at most 90 nights.

    Each price shown from today on is stored as a snapshot. A night whose model
    and inputs (events, days booked ahead) match its latest snapshot returns
    that snapshot; otherwise it's priced and a new snapshot is stored. Days
    booked ahead change daily, so a future night gets a new snapshot each day
    it's shown. Past nights are never stored after the fact: one with a
    snapshot returns it as it was, one without is priced and returned unsaved.
    404 if the hotel has no active model.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        session (SessionDep): The database session.
        stay_date (date | None): One night; the query key is `date`, but
            that name is taken by the type.
        start (date | None): First night, inclusive.
        end (date | None): Last night, inclusive; None for `start` alone.

    Returns:
        list[RecommendationResponse]: One per night.

    Raises:
        InvalidRequestError: Both `date` and a range, neither, a bad range,
            or another room type.
        NotFoundError: The hotel has no active model.
    """
    if stay_date is not None and (start is not None or end is not None):
        raise InvalidRequestError("send `date`, or `start` and `end`, not both")
    first = stay_date or start
    if first is None:
        raise InvalidRequestError("send `date`, or `start` and `end`")
    recommendations = await recommendation_service.get_recommendations(
        session, hotel_id, start=first, end=end or first
    )
    return [RecommendationResponse.model_validate(r) for r in recommendations]
