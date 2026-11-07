# Import all models here so Alembic can detect them

from foresight.database.base import Base
from foresight.database.models.booking import Booking, BookingCancellation
from foresight.database.models.city import City
from foresight.database.models.example_widget import Widget
from foresight.database.models.feedback import Feedback
from foresight.database.models.hotel import DailyPerformance, Hotel, RoomType
from foresight.database.models.job import Job
from foresight.database.models.pricing_model import PricingModel, PricingModelFeedback
from foresight.database.models.recommendation import RecommendationSnapshot
from foresight.database.models.signals.event import Event, EventObservation
from foresight.database.models.signals.weather import Weather
from foresight.database.models.user import User, UserHotel

__all__ = [
    "Base",
    "Booking",
    "BookingCancellation",
    "City",
    "DailyPerformance",
    "Event",
    "EventObservation",
    "Feedback",
    "Hotel",
    "Job",
    "PricingModel",
    "PricingModelFeedback",
    "RoomType",
    "User",
    "UserHotel",
    "Weather",
    "RecommendationSnapshot",
    "Widget",
]
