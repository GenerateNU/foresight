"""Data access for `feedback`: the manager's view of a night, one row per version."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from foresight.database.models.feedback import Feedback

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.enums import (
        FeedbackReasonTag,
        FeedbackTiming,
        FeedbackVerdict,
    )


async def create_feedback(
    session: AsyncSession,
    *,
    hotel_id: int,
    room_type_id: int,
    stay_date: date,
    snapshot_id: int | None,
    user_id: int | None,
    verdict: FeedbackVerdict,
    rate: Decimal | None,
    reason_tags: list[FeedbackReasonTag],
    reason_text: str | None,
    timing: FeedbackTiming,
) -> Feedback | None:
    """Add the next version of a night's feedback. Never updates a row.

    The version is worked out in the insert itself. None if another version
    with the same number was added at the same moment, so nothing is lost
    silently; the caller can ask for it to be sent again.
    """
    next_version = (
        select(func.coalesce(func.max(Feedback.version), 0) + 1)
        .where(
            Feedback.hotel_id == hotel_id,
            Feedback.room_type_id == room_type_id,
            Feedback.stay_date == stay_date,
        )
        .scalar_subquery()
    )
    return await session.scalar(
        insert(Feedback)
        .values(
            hotel_id=hotel_id,
            room_type_id=room_type_id,
            stay_date=stay_date,
            version=next_version,
            snapshot_id=snapshot_id,
            user_id=user_id,
            verdict=verdict,
            rate=rate,
            reason_tags=reason_tags,
            reason_text=reason_text,
            timing=timing,
        )
        .on_conflict_do_nothing(
            constraint="uq_feedback_hotel_id_room_type_id_stay_date_version"
        )
        .returning(Feedback)
    )


async def list_feedback(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date,
    end: date,
    room_type_id: int | None,
    include_history: bool,
) -> Sequence[Feedback]:
    """Feedback for the nights in [start, end], oldest night first.

    Only the current (highest) version of each room type's night, unless
    `include_history`, which also returns the earlier versions, oldest first.
    """
    stmt = select(Feedback).where(
        Feedback.hotel_id == hotel_id, Feedback.stay_date.between(start, end)
    )
    if room_type_id is not None:
        stmt = stmt.where(Feedback.room_type_id == room_type_id)
    if include_history:
        stmt = stmt.order_by(
            Feedback.stay_date, Feedback.room_type_id, Feedback.version
        )
    else:
        stmt = stmt.distinct(Feedback.stay_date, Feedback.room_type_id).order_by(
            Feedback.stay_date, Feedback.room_type_id, Feedback.version.desc()
        )
    return (await session.scalars(stmt)).all()
