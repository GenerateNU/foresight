# Import all models here so Alembic can detect them

from foresight.database.base import Base
from foresight.database.models.competitor_rate import CompetitorRate
from foresight.database.models.event import Event, EventObservation
from foresight.database.models.example_widget import Widget
from foresight.database.models.flight import FlightArrival
from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.database.models.pricing_model import PricingModel
from foresight.database.models.weather import Weather

__all__ = [
    "Base",
    "CompetitorRate",
    "DailyPerformance",
    "Event",
    "EventObservation",
    "FlightArrival",
    "Hotel",
    "PricingModel",
    "RoomType",
    "Weather",
    "Widget",
]
