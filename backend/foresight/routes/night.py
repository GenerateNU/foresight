"""What each night holds: the events affecting it, and rates across a range."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Path, Query
from pydantic import Field

from foresight.database.enums import EventCategory
from foresight.routes.helpers import ResponseSchema, SessionDep
from foresight.services.domain import night as night_service

router = APIRouter(tags=["Nights"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


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


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/hotels/{hotel_id}/nights/{stay_date}", response_model=NightResponse)
async def get_night(
    hotel_id: HotelId,
    session: SessionDep,
    stay_date: Annotated[
        date,
        Path(description="The night. YYYY-MM-DD", examples=["2025-01-01"]),
    ],
) -> NightResponse:
    """The events affecting one night, with full details. A multi-day event
    shows on each of its nights as day N of M."""
    night = await night_service.get_night(session, hotel_id, stay_date)
    return NightResponse.model_validate(night)


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
