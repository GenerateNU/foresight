"""API shapes for hotel data."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field


class HotelCreate(BaseModel):
    name: str
    city: str
    total_rooms: int
    latitude: float | None = None
    longitude: float | None = None


class HotelRead(HotelCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class RoomTypeCreate(BaseModel):
    hotel_id: int
    name: str
    room_count: int
    base_rate: Decimal


class RoomTypeRead(RoomTypeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class DailyPerformanceCreate(BaseModel):
    room_type_id: int
    stay_date: date
    rate: Decimal | None = None
    rooms_available: int
    rooms_sold: int = 0
    room_revenue: Decimal = Decimal("0")


class DailyPerformanceRead(DailyPerformanceCreate):
    """Adds the three standard hotel metrics, calculated rather than stored."""

    model_config = ConfigDict(from_attributes=True)

    id: int

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
