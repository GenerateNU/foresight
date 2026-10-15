"""Events in a hotel's city."""

from datetime import date, datetime

from fastapi import APIRouter
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


class EventResponse(ResponseSchema):
    """A merged event. Raw per-source sightings (`event_observations`) stay internal."""

    id: int
    title: str
    category: EventCategory
    venue: str | None
    city_id: int
    country: str | None
    latitude: float | None
    longitude: float | None
    start_local_date: date = Field(description="Local to the event, not UTC")
    end_local_date: date = Field(description="Inclusive")
    start_at_utc: datetime | None
    end_at_utc: datetime | None
    timezone: str
    date_precision: DatePrecision
    expected_attendance: int | None
    impact_rank: int | None = Field(description="PredictHQ rank, 0-100")
    local_rank: int | None = Field(description="PredictHQ local rank, 0-100")
    confidence: float = Field(description="1.0 for listings; lower when extracted")
    status: EventStatus
    url: str | None
    primary_source: Source = Field(description="Whose values the row carries")
    first_seen_at: datetime
    last_seen_at: datetime


@router.get("/hotels/{hotel_id}/events", response_model=PageResponse[EventResponse])
async def list_events(
    hotel_id: int,
    session: SessionDep,
    page: PageDep,
    start: date | None = None,
    end: date | None = None,
) -> PageResponse[EventResponse]:
    """Events in the hotel's city overlapping the date range; cancelled and
    deleted events are hidden."""
    rows, total = await event_service.list_events(
        session, hotel_id, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(EventResponse, rows, total, page)
