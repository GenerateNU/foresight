"""Flight arrivals at the airport of a hotel's city."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Path, Query
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


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class FlightArrivalResponse(ResponseSchema):
    id: int = Field(description="The row's id")
    city_id: int = Field(description="The city the airport serves")
    airport: str = Field(description="IATA or ICAO, as the source reports it")
    arrival_date: date = Field(description="The day, local to the city")
    flight_count: int | None = Field(description="Arriving flights; null if unknown")
    avg_fare_eur: Decimal | None = Field(
        description="Average fare, in EUR; null if unknown"
    )
    source: str = Field(description="Each source keeps its own row per day")
    captured_at: datetime = Field(description="When this row was last fetched, UTC")


HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get(
    "/hotels/{hotel_id}/flight-arrivals",
    response_model=PageResponse[FlightArrivalResponse],
)
async def list_flight_arrivals(
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
) -> PageResponse[FlightArrivalResponse]:
    """Daily arrivals at the airport of the hotel's city. Each source keeps its
    own row per day."""
    rows, total = await flight_service.list_flight_arrivals(
        session, hotel_id, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(FlightArrivalResponse, rows, total, page)
