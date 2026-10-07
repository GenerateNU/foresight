# Import all models here so Alembic can detect them

from foresight.database.base import Base
from foresight.database.models.external import (
    CompetitorRate,
    Event,
    EventObservation,
    FlightArrival,
    Weather,
)
from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType

__all__ = [
    "Base",
    "CompetitorRate",
    "DailyPerformance",
    "Event",
    "EventObservation",
    "FlightArrival",
    "Hotel",
    "RoomType",
    "Weather",
]
