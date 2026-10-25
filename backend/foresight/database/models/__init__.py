# Import all models here so Alembic can detect them

from foresight.database.base import Base
from foresight.database.models.city import City
from foresight.database.models.example_widget import Widget
from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.database.models.job import Job
from foresight.database.models.pricing_model import PricingModel
from foresight.database.models.recommendation import RecommendationSnapshot
from foresight.database.models.signals.competitor_rate import CompetitorRate
from foresight.database.models.signals.event import Event, EventObservation
from foresight.database.models.signals.flight import FlightArrival
from foresight.database.models.signals.weather import Weather

__all__ = [
    "Base",
    "City",
    "CompetitorRate",
    "DailyPerformance",
    "Event",
    "EventObservation",
    "FlightArrival",
    "Hotel",
    "Job",
    "PricingModel",
    "RoomType",
    "Weather",
    "RecommendationSnapshot",
    "Widget",
]
