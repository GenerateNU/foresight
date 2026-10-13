from datetime import date, datetime
from decimal import Decimal

from foresight.ingest.normalize import (
    DatePrecision,
    EventCategory,
    EventStatus,
    Source,
)
from foresight.schemas.base import ResponseSchema


class WeatherResponse(ResponseSchema):
    id: int
    city: str
    weather_date: date
    temp_max_c: float | None
    temp_min_c: float | None
    precip_mm: float | None
    wind_kph: float | None
    condition: str | None
    is_forecast: bool
    source: str
    captured_at: datetime


class EventResponse(ResponseSchema):
    """A merged event. Raw per-source sightings (`event_observations`) stay internal."""

    id: int
    title: str
    category: EventCategory
    venue: str | None
    city: str
    country: str | None
    latitude: float | None
    longitude: float | None
    start_local_date: date
    end_local_date: date  # inclusive
    start_at_utc: datetime | None
    end_at_utc: datetime | None
    timezone: str
    date_precision: DatePrecision
    expected_attendance: int | None
    impact_rank: int | None
    local_rank: int | None
    confidence: float
    status: EventStatus
    url: str | None
    primary_source: Source
    first_seen_at: datetime
    last_seen_at: datetime


class FlightArrivalResponse(ResponseSchema):
    id: int
    airport: str
    arrival_date: date
    flight_count: int | None
    avg_fare_eur: Decimal | None
    source: str
    captured_at: datetime
