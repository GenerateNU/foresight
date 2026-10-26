"""Weather for a hotel's city, and how completely it's been backfilled."""

from datetime import date, datetime
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
from foresight.services.domain import weather as weather_service
from foresight.services.domain import weather_coverage as coverage_service

router = APIRouter(tags=["Weather"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class WeatherResponse(ResponseSchema):
    id: int = Field(description="The row's id")
    city_id: int = Field(description="The city described")
    weather_date: date = Field(description="The day described, local to the city")
    temp_max_c: float | None = Field(description="Daily high, °C; null if unknown")
    temp_min_c: float | None = Field(description="Daily low, °C; null if unknown")
    precip_mm: float | None = Field(description="Rain and snow, mm; null if unknown")
    wind_kph: float | None = Field(description="Peak wind, km/h; null if unknown")
    condition: str | None = Field(
        description="Summary of the day; null if unknown",
        examples=["rain", "cloudy"],
    )
    is_forecast: bool = Field(
        description="True for a forecast (may be revised), false for recorded"
    )
    source: str = Field(description="Where the row came from", examples=["open-meteo"])
    captured_at: datetime = Field(description="When this row was last fetched, UTC")


class DateSpanResponse(ResponseSchema):
    first: date = Field(description="First day, inclusive")
    last: date = Field(description="Last day, inclusive")


class WeatherCoverageResponse(ResponseSchema):
    city_id: int = Field(description="The city checked")
    start: date = Field(description="First day checked, inclusive")
    end: date = Field(description="Last day checked, inclusive")
    days: int = Field(description="Days in the window")
    rows: int = Field(description="Days with a recorded row saved")
    earliest: date | None = Field(description="First day with values")
    missing: list[DateSpanResponse] = Field(description="Days with no row at all")
    empty: list[DateSpanResponse] = Field(
        description="Rows saved without values, usually the archive's lag"
    )


HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/hotels/{hotel_id}/weather", response_model=PageResponse[WeatherResponse])
async def list_weather(
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
) -> PageResponse[WeatherResponse]:
    """Daily weather for the hotel's city. Forecast and recorded rows are both
    returned; `is_forecast` tells them apart."""
    rows, total = await weather_service.list_weather(
        session, hotel_id, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(WeatherResponse, rows, total, page)


@router.get(
    "/hotels/{hotel_id}/coverage/weather", response_model=WeatherCoverageResponse
)
async def weather_coverage(
    hotel_id: HotelId,
    session: SessionDep,
    start: Annotated[
        date | None,
        Query(
            description="First day, inclusive. YYYY-MM-DD. Omit for the hotel's "
            "first loaded night",
            examples=["2025-01-01"],
        ),
    ] = None,
    end: Annotated[
        date | None,
        Query(
            description="Last day, inclusive. YYYY-MM-DD. Omit for the hotel's "
            "last loaded night",
            examples=["2025-12-31"],
        ),
    ] = None,
) -> WeatherCoverageResponse:
    """Days with recorded weather in the window, and the gaps. Dates default to
    the hotel's loaded stay dates."""
    report = await coverage_service.hotel_weather_coverage(
        session, hotel_id, start=start, end=end
    )
    return WeatherCoverageResponse.model_validate(report)
