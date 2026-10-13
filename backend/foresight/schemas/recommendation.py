from datetime import date
from decimal import Decimal
from typing import Literal

from foresight.schemas.base import ResponseSchema


class FactorResponse(ResponseSchema):
    """One signal's pull on the recommended rate."""

    signal: str  # e.g. "events", "weather", "flights"
    direction: Literal["up", "down", "neutral"]
    detail: str


class ExplanationResponse(ResponseSchema):
    summary: str
    factors: list[FactorResponse]


class ConfidenceIntervalResponse(ResponseSchema):
    lower: Decimal
    upper: Decimal
    level: float  # coverage, e.g. 0.95


class RecommendationResponse(ResponseSchema):
    hotel_id: int
    stay_date: date
    recommended_rate: Decimal
    currency: str
    explanation: ExplanationResponse
    confidence_interval: ConfidenceIntervalResponse
    model_version: str
    is_placeholder: bool  # true until the pricing model is wired in
