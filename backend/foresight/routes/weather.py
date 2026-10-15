"""Weather for a hotel's city, and how completely it's been backfilled."""

from datetime import date, datetime

from fastapi import APIRouter
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


class WeatherResponse(ResponseSchema):
    id: int
    city_id: int
    weather_date: date = Field(description="The local day described")
    temp_max_c: float | None
    temp_min_c: float | None
    precip_mm: float | None
    wind_kph: float | None
    condition: str | None = Field(description='e.g. "rain", "cloudy"')
    is_forecast: bool = Field(
        description="True for a forecast (may be revised), false for recorded"
    )
    source: str
    captured_at: datetime = Field(description="When this row was last fetched")


class DateSpanResponse(ResponseSchema):
    first: date
    last: date = Field(description="Inclusive")


class WeatherCoverageResponse(ResponseSchema):
    city_id: int
    start: date
    end: date
    days: int = Field(description="Days in the window")
    rows: int = Field(description="Days with a recorded row saved")
    earliest: date | None = Field(description="First day with values")
    missing: list[DateSpanResponse] = Field(description="Days with no row at all")
    empty: list[DateSpanResponse] = Field(
        description="Rows saved without values, usually the archive's lag"
    )


@router.get("/hotels/{hotel_id}/weather", response_model=PageResponse[WeatherResponse])
async def list_weather(
    hotel_id: int,
    session: SessionDep,
    page: PageDep,
    start: date | None = None,
    end: date | None = None,
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
    hotel_id: int,
    session: SessionDep,
    start: date | None = None,
    end: date | None = None,
) -> WeatherCoverageResponse:
    """Days with recorded weather in the window, and the gaps. Dates default to
    the hotel's loaded stay dates."""
    report = await coverage_service.hotel_weather_coverage(
        session, hotel_id, start=start, end=end
    )
    return WeatherCoverageResponse.model_validate(report)
