"""Freshness: when each kind of data last refreshed for a hotel."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import Field

from foresight.routes.helpers import ResponseSchema, SessionDep
from foresight.services.domain import freshness as freshness_service

router = APIRouter(tags=["Freshness"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class KindFreshnessResponse(ResponseSchema):
    last_success: datetime | None = Field(
        description="When it last succeeded, UTC; null if it never has"
    )
    last_failure: datetime | None = Field(
        description="When the latest attempt failed or stopped, UTC; null if "
        "the latest attempt succeeded or it never ran"
    )
    error: str | None = Field(description="Why the latest attempt failed; null if not")
    stale: bool = Field(
        description="Never succeeded, or the last success is too old: 1 day for "
        "events and weather, 7 for hotel data, 30 for training"
    )


class FreshnessResponse(ResponseSchema):
    events: KindFreshnessResponse = Field(description="Routine events refresh")
    weather: KindFreshnessResponse = Field(description="Routine forecast refresh")
    hotel_data: KindFreshnessResponse = Field(description="Hotel data upload (CSV)")
    training: KindFreshnessResponse = Field(description="Pricing model training")
    recommendations: KindFreshnessResponse | None = Field(
        description="Recommendation snapshots; always null until they're stored"
    )


HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/hotels/{hotel_id}/freshness", response_model=FreshnessResponse)
async def get_freshness(hotel_id: HotelId, session: SessionDep) -> FreshnessResponse:
    """When each kind of data last refreshed, and whether it's stale."""
    result = await freshness_service.get_freshness(session, hotel_id)
    return FreshnessResponse.model_validate(result)
