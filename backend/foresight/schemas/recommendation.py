"""API shape for a room-rate recommendation.

This is the final contract; the model that fills it in comes later.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class RecommendationFactor(BaseModel):
    """One signal's pull on the recommended rate."""

    signal: str  # e.g. "events", "weather", "flights"
    direction: Literal["up", "down", "neutral"]
    detail: str


class RecommendationExplanation(BaseModel):
    summary: str
    factors: list[RecommendationFactor]


class ConfidenceInterval(BaseModel):
    lower: Decimal
    upper: Decimal
    level: float  # coverage, e.g. 0.95


class RecommendationRead(BaseModel):
    hotel_id: int
    stay_date: date
    recommended_rate: Decimal
    currency: str
    explanation: RecommendationExplanation
    confidence_interval: ConfidenceInterval
    model_version: str
    is_placeholder: bool  # true until the pricing model is wired in
