"""API shapes for hotel data."""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, computed_field, field_validator

from foresight.schemas.base import RequestSchema, ResponseSchema


class HotelRequest(RequestSchema):
    name: str
    city: str
    total_rooms: int
    latitude: float | None = None
    longitude: float | None = None
    airport_iata: str | None = Field(default=None, min_length=3, max_length=3)
    airport_icao: str | None = Field(default=None, min_length=4, max_length=4)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"unknown IANA timezone {value!r}") from None
        return value


class HotelResponse(ResponseSchema):
    id: int
    name: str
    city: str
    total_rooms: int
    latitude: float | None
    longitude: float | None
    airport_iata: str | None
    airport_icao: str | None
    timezone: str | None


class RoomTypeRequest(RequestSchema):
    hotel_id: int
    name: str
    room_count: int
    base_rate: Decimal


class RoomTypeResponse(ResponseSchema):
    id: int
    hotel_id: int
    name: str
    room_count: int
    base_rate: Decimal


class DailyPerformanceRequest(RequestSchema):
    room_type_id: int
    stay_date: date
    rate: Decimal | None = None
    rooms_available: int
    rooms_sold: int = 0
    room_revenue: Decimal = Decimal("0")


class DailyPerformanceResponse(ResponseSchema):
    """Adds the three standard hotel metrics, calculated rather than stored."""

    id: int
    room_type_id: int
    stay_date: date
    rate: Decimal | None
    rooms_available: int
    rooms_sold: int
    room_revenue: Decimal

    @computed_field
    @property
    def occupancy(self) -> float | None:
        """Share of rooms sold, 0-1."""
        if not self.rooms_available:
            return None
        return round(self.rooms_sold / self.rooms_available, 4)

    @computed_field
    @property
    def adr(self) -> Decimal | None:
        """Average Daily Rate: revenue per room sold."""
        if not self.rooms_sold:
            return None
        return round(self.room_revenue / self.rooms_sold, 2)

    @computed_field
    @property
    def revpar(self) -> Decimal | None:
        """Revenue Per Available Room: revenue per room we had to sell."""
        if not self.rooms_available:
            return None
        return round(self.room_revenue / self.rooms_available, 2)
