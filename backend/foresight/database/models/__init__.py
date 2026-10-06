# Import all models here so Alembic can detect them

from foresight.database.base import Base
from foresight.database.models.example_widget import Widget
from foresight.database.models.external import (
    CompetitorRate,
    Event,
    FlightArrival,
    Weather,
)
from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType

__all__ = [
    "Base",
    "CompetitorRate",
    "DailyPerformance",
    "Event",
    "FlightArrival",
    "Hotel",
    "RoomType",
    "Weather",
    "Widget",
]
