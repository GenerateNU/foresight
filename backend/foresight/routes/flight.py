"""Flight arrivals at the airport of a hotel's city."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter
from pydantic import Field

from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services.domain import flight as flight_service

router = APIRouter(tags=["Flights"])


class FlightArrivalResponse(ResponseSchema):
    id: int
    city_id: int
    airport: str = Field(description="IATA or ICAO, as the source reports it")
    arrival_date: date
    flight_count: int | None
    avg_fare_eur: Decimal | None
    source: str = Field(description="Each source keeps its own row per day")
    captured_at: datetime


@router.get(
    "/hotels/{hotel_id}/flight-arrivals",
    response_model=PageResponse[FlightArrivalResponse],
)
async def list_flight_arrivals(
    hotel_id: int,
    session: SessionDep,
    page: PageDep,
    start: date | None = None,
    end: date | None = None,
) -> PageResponse[FlightArrivalResponse]:
    """Daily arrivals at the airport of the hotel's city. Each source keeps its
    own row per day."""
    rows, total = await flight_service.list_flight_arrivals(
        session, hotel_id, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(FlightArrivalResponse, rows, total, page)
