"""The manager's feedback on a night's rate: add it, change it, list it."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import Field

from foresight.database.enums import (
    FeedbackReasonTag,
    FeedbackTiming,
    FeedbackVerdict,
)
from foresight.routes.access import CurrentUserDep, HotelId
from foresight.routes.helpers import RequestSchema, ResponseSchema, SessionDep
from foresight.services.domain import feedback as feedback_service

router = APIRouter(tags=["Feedback"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class FeedbackRequest(RequestSchema):
    """Sending feedback for a night that already has some adds a new version;
    the earlier ones are kept."""

    room_type_id: int = Field(
        description="The room type the feedback is about; see /hotels/{id}/room-types",
        examples=[1],
    )
    stay_date: date = Field(
        description="The night, local to the hotel's city, past or future. YYYY-MM-DD",
        examples=["2025-01-01"],
    )
    rate: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=2,
        description="The nightly rate the manager chose to charge, in EUR. Compared "
        "with the recommendation to set the verdict",
        examples=["210.00"],
    )
    reason_tags: list[FeedbackReasonTag] = Field(
        default_factory=list,
        description="Why, from a fixed list; any number, or none. Repeats count once",
    )
    reason_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="Why, in the manager's words; null if none",
    )
    snapshot_id: int = Field(
        description="The `snapshot_id` that /hotels/{id}/recommendations returned "
        "for this night, i.e. the rate the manager saw",
        examples=[1],
    )


class FeedbackResponse(ResponseSchema):
    id: int = Field(description="The feedback's id")
    hotel_id: int = Field(description="The hotel it belongs to")
    room_type_id: int = Field(description="The room type it is about")
    stay_date: date = Field(description="The night, local to the hotel's city")
    version: int = Field(
        description="1 for the first feedback on this room type and night, then "
        "one more for each change; the highest is the current one"
    )
    snapshot_id: int | None = Field(
        description="The recommendation the manager saw; null on feedback saved "
        "before one was required, or if the snapshot was deleted"
    )
    user_id: int | None = Field(
        description="Who gave it; null for feedback saved before sign-in was required"
    )
    verdict: FeedbackVerdict = Field(
        description="Whether our recommendation was too high, too low or about "
        "right; set by the server by comparing `rate` with it"
    )
    rate: Decimal | None = Field(
        description="The rate the manager chose, in EUR; null only on feedback "
        "saved before a rate was required"
    )
    reason_tags: list[FeedbackReasonTag] = Field(description="Why, from a fixed list")
    reason_text: str | None = Field(description="Why, in their words; null if none")
    timing: FeedbackTiming = Field(
        description="Whether it was given before the night or after it; set by "
        "the server from the night's date"
    )
    created_at: datetime = Field(description="When this version was given, UTC")


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post(
    "/hotels/{hotel_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_feedback(
    hotel_id: HotelId,
    data: FeedbackRequest,
    session: SessionDep,
    user: CurrentUserDep,
) -> FeedbackResponse:
    """Record the rate the manager chose for a night, or change it.

    Send it only when the manager changes our rate: a night with no feedback
    keeps the recommendation. Nothing is overwritten: a change is a new
    version, and the highest version is the current one. 404 for an unknown
    hotel, or a room type or snapshot that isn't the hotel's; 422 for a missing
    rate or snapshot, a rate of 0 or less, or a snapshot from another night.
    """
    feedback = await feedback_service.add_feedback(
        session, hotel_id, user_id=user.id, **data.model_dump()
    )
    return FeedbackResponse.model_validate(feedback)


@router.get("/hotels/{hotel_id}/feedback", response_model=list[FeedbackResponse])
async def list_feedback(
    hotel_id: HotelId,
    session: SessionDep,
    start: Annotated[
        date,
        Query(
            description="First night, inclusive. YYYY-MM-DD", examples=["2025-01-01"]
        ),
    ],
    end: Annotated[
        date,
        Query(
            description="Last night, inclusive. YYYY-MM-DD; at most 366 nights",
            examples=["2025-01-31"],
        ),
    ],
    room_type_id: Annotated[
        int | None,
        Query(description="Only this room type; omit for all", examples=[1]),
    ] = None,
    include_history: Annotated[
        bool,
        Query(
            description="Also return each night's earlier versions, oldest first, "
            "with their times; otherwise only the current one"
        ),
    ] = False,
) -> list[FeedbackResponse]:
    """The current feedback for each night from `start` to `end`, oldest night
    first. Nights with none are left out."""
    feedback = await feedback_service.list_feedback(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_id=room_type_id,
        include_history=include_history,
    )
    return [FeedbackResponse.model_validate(f) for f in feedback]
