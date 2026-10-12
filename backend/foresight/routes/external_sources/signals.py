"""HTTP layer for the read-only external signals.

Keyed by `city` or `airport`, not by hotel: signal rows carry no hotel id.
`start`/`end` are inclusive and optional.
"""

from datetime import date

from fastapi import APIRouter

from foresight.routes.common import PageDep, SessionDep, paginate
from foresight.schemas.common import Page
from foresight.schemas.signals import EventRead, FlightArrivalRead, WeatherRead
from foresight.services import signals as signals_service

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/weather", response_model=Page[WeatherRead])
async def list_weather(
    session: SessionDep,
    page: PageDep,
    city: str,
    start: date | None = None,
    end: date | None = None,
) -> Page[WeatherRead]:
    """Daily weather for a city. Forecast and recorded rows are both returned."""
    rows, total = await signals_service.list_weather(
        session, city=city, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(WeatherRead, rows, total, page)


@router.get("/events", response_model=Page[EventRead])
async def list_events(
    session: SessionDep,
    page: PageDep,
    city: str,
    start: date | None = None,
    end: date | None = None,
) -> Page[EventRead]:
    """Events in a city overlapping the date range; cancelled/deleted are hidden."""
    rows, total = await signals_service.list_events(
        session, city=city, start=start, end=end, limit=page.limit, offset=page.offset
    )
    return paginate(EventRead, rows, total, page)


@router.get("/flight-arrivals", response_model=Page[FlightArrivalRead])
async def list_flight_arrivals(
    session: SessionDep,
    page: PageDep,
    airport: str,
    start: date | None = None,
    end: date | None = None,
) -> Page[FlightArrivalRead]:
    """Arrivals for an airport code exactly as stored (sources differ: DUB, EIDW)."""
    rows, total = await signals_service.list_flight_arrivals(
        session,
        airport=airport,
        start=start,
        end=end,
        limit=page.limit,
        offset=page.offset,
    )
    return paginate(FlightArrivalRead, rows, total, page)
