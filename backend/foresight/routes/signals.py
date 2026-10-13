from datetime import date

from fastapi import APIRouter

from foresight.routes.common import PageDep, SessionDep, paginate
from foresight.schemas.common import PageResponse
from foresight.schemas.signals import (
    EventResponse,
    FlightArrivalResponse,
    WeatherResponse,
)
from foresight.services import signals as signals_service

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/weather", response_model=PageResponse[WeatherResponse])
async def list_weather(
    session: SessionDep,
    page: PageDep,
    city: str,
    start: date | None = None,
    end: date | None = None,
) -> PageResponse[WeatherResponse]:
    """Daily weather for a city. Forecast and recorded rows are both returned."""
    rows, total = await signals_service.list_weather(
        session, city=city, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(WeatherResponse, rows, total, page)


@router.get("/events", response_model=PageResponse[EventResponse])
async def list_events(
    session: SessionDep,
    page: PageDep,
    city: str,
    start: date | None = None,
    end: date | None = None,
) -> PageResponse[EventResponse]:
    """Events in a city overlapping the date range; cancelled/deleted are hidden."""
    rows, total = await signals_service.list_events(
        session, city=city, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(EventResponse, rows, total, page)


@router.get("/flight-arrivals", response_model=PageResponse[FlightArrivalResponse])
async def list_flight_arrivals(
    session: SessionDep,
    page: PageDep,
    airport: str,
    start: date | None = None,
    end: date | None = None,
) -> PageResponse[FlightArrivalResponse]:
    """Arrivals for an airport code exactly as stored (sources differ: DUB, EIDW)."""
    rows, total = await signals_service.list_flight_arrivals(
        session,
        airport=airport,
        start=start,
        end=end,
        limit=page.limit,
        offset=page.offset,
    )
    return paginate(FlightArrivalResponse, rows, total, page)
