"""Nightly rate recommendations.

Returns domain dataclasses; the route maps them to `RecommendationResponse`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class Factor:
    """One signal's pull on the recommended rate."""

    signal: str  # e.g. "events", "weather", "flights"
    direction: Literal["up", "down", "neutral"]
    detail: str


@dataclass(frozen=True, slots=True)
class Explanation:
    summary: str
    factors: list[Factor]


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: Decimal
    upper: Decimal
    level: float  # coverage, e.g. 0.95


@dataclass(frozen=True, slots=True)
class Recommendation:
    hotel_id: int
    stay_date: date
    recommended_rate: Decimal
    currency: str
    explanation: Explanation
    confidence_interval: ConfidenceInterval
    model_version: str
    is_placeholder: bool  # true until the pricing model is wired in


async def get_recommendation(
    session: AsyncSession, hotel_id: int, stay_date: date
) -> Recommendation:
    """The recommendation for one night. Raises NotFoundError for an unknown hotel."""
    await get_hotel(session, hotel_id)
    return _placeholder(hotel_id, stay_date)


def _placeholder(hotel_id: int, stay_date: date) -> Recommendation:
    return Recommendation(
        hotel_id=hotel_id,
        stay_date=stay_date,
        recommended_rate=Decimal("150.00"),
        currency="EUR",
        explanation=Explanation(
            summary="Placeholder recommendation; the pricing model isn't wired in yet.",
            factors=[
                Factor(
                    signal="events",
                    direction="neutral",
                    detail="Placeholder: nearby events are not yet considered.",
                ),
                Factor(
                    signal="weather",
                    direction="neutral",
                    detail="Placeholder: the forecast is not yet considered.",
                ),
                Factor(
                    signal="flights",
                    direction="neutral",
                    detail="Placeholder: flight arrivals are not yet considered.",
                ),
            ],
        ),
        confidence_interval=ConfidenceInterval(
            lower=Decimal("135.00"), upper=Decimal("165.00"), level=0.95
        ),
        model_version="stub-0",
        is_placeholder=True,
    )
