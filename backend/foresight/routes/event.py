"""Events in a hotel's city."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query
from pydantic import Field

from foresight.database.enums import DatePrecision, EventCategory, EventStatus, Source
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services.domain import event as event_service

router = APIRouter(tags=["Events"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class EventResponse(ResponseSchema):
    """A merged event. Raw per-source sightings (`event_observations`) stay internal."""

    id: int = Field(description="The event's id")
    title: str = Field(description="The event's name")
    category: EventCategory = Field(description="What kind of event it is")
    venue: str | None = Field(description="Where it's held; null if unknown")
    city_id: int = Field(description="The city it's in")
    country: str | None = Field(description="ISO-3166 alpha-2 code; null if unknown")
    latitude: float | None = Field(description="The venue, in degrees; null if unknown")
    longitude: float | None = Field(
        description="The venue, in degrees; null if unknown"
    )
    start_local_date: date = Field(description="First day, local to the event")
    end_local_date: date = Field(description="Last day, inclusive, local to the event")
    start_at_utc: datetime | None = Field(
        description="Start time, UTC; null if unknown"
    )
    end_at_utc: datetime | None = Field(description="End time, UTC; null if unknown")
    timezone: str = Field(description="IANA timezone of the event")
    date_precision: DatePrecision = Field(
        description="How precisely the source pinned the date"
    )
    expected_attendance: int | None = Field(
        description="Predicted people; null if unknown"
    )
    impact_rank: int | None = Field(description="PredictHQ rank, 0-100")
    local_rank: int | None = Field(description="PredictHQ local rank, 0-100")
    confidence: float = Field(description="1.0 for listings; lower when extracted")
    status: EventStatus = Field(description="Whether it's still going ahead")
    url: str | None = Field(description="Link to the source; null if none")
    primary_source: Source = Field(description="Whose values the row carries")
    first_seen_at: datetime = Field(
        description="When any source first reported it, UTC"
    )
    last_seen_at: datetime = Field(description="When a source last reported it, UTC")


HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/hotels/{hotel_id}/events", response_model=PageResponse[EventResponse])
async def list_events(
    hotel_id: HotelId,
    session: SessionDep,
    page: PageDep,
    start: Annotated[
        date | None,
        Query(
            description="First day, inclusive. YYYY-MM-DD",
            examples=["2025-01-01"],
        ),
    ] = None,
    end: Annotated[
        date | None,
        Query(
            description="Last day, inclusive. YYYY-MM-DD",
            examples=["2025-12-31"],
        ),
    ] = None,
) -> PageResponse[EventResponse]:
    """Events in the hotel's city overlapping the date range; cancelled and
    deleted events are hidden."""
    rows, total = await event_service.list_events(
        session, hotel_id, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(EventResponse, rows, total, page)
