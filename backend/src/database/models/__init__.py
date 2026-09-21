# Import all models here so Alembic can detect them

from database.base import Base
from database.models.external import CompetitorRate, Event, FlightArrival, Weather
from database.models.hotel import DailyPerformance, Hotel, RoomType

__all__ = [
    "Base",
    "CompetitorRate",
    "DailyPerformance",
    "Event",
    "FlightArrival",
    "Hotel",
    "RoomType",
    "Weather",
]
