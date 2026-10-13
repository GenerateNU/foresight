from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.repository import hotel as hotel_repo
from foresight.schemas.recommendation import (
    ConfidenceIntervalResponse,
    ExplanationResponse,
    FactorResponse,
    RecommendationResponse,
)


def _placeholder(hotel_id: int, stay_date: date) -> RecommendationResponse:
    return RecommendationResponse(
        hotel_id=hotel_id,
        stay_date=stay_date,
        recommended_rate=Decimal("150.00"),
        currency="EUR",
        explanation=ExplanationResponse(
            summary="Placeholder recommendation; the pricing model isn't wired in yet.",
            factors=[
                FactorResponse(
                    signal="events",
                    direction="neutral",
                    detail="Placeholder: nearby events are not yet considered.",
                ),
                FactorResponse(
                    signal="weather",
                    direction="neutral",
                    detail="Placeholder: the forecast is not yet considered.",
                ),
                FactorResponse(
                    signal="flights",
                    direction="neutral",
                    detail="Placeholder: flight arrivals are not yet considered.",
                ),
            ],
        ),
        confidence_interval=ConfidenceIntervalResponse(
            lower=Decimal("135.00"), upper=Decimal("165.00"), level=0.95
        ),
        model_version="stub-0",
        is_placeholder=True,
    )


async def get_recommendation(
    session: AsyncSession, hotel_id: int, stay_date: date
) -> RecommendationResponse | None:
    """The recommendation for one night, or `None` if the hotel doesn't exist."""
    if await hotel_repo.get_hotel(session, hotel_id) is None:
        return None
    return _placeholder(hotel_id, stay_date)
