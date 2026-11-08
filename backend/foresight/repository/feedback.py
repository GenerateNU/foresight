"""Data access for `feedback`: the manager's view of a night, one row per version."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from foresight.database.enums import FeedbackTiming
from foresight.database.models.feedback import Feedback
from foresight.database.models.hotel import RoomType

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.enums import FeedbackReasonTag, FeedbackVerdict


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


async def training_feedback(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> Sequence[Mapping[str, Any]]:
    """The feedback a training run may use, one row per room type and night.

    Takes each night's current (highest) version, and keeps it only if it was
    given after the night: a night whose current version is from before it has
    no feedback that training can use (decision 0044). Rows carry id,
    stay_date, room_type (its name), verdict and rate.
    """
    current = select(Feedback).where(Feedback.hotel_id == hotel_id)
    if start is not None:
        current = current.where(Feedback.stay_date >= start)
    if end is not None:
        current = current.where(Feedback.stay_date <= end)
    current = (
        current.distinct(Feedback.room_type_id, Feedback.stay_date)
        .order_by(Feedback.room_type_id, Feedback.stay_date, Feedback.version.desc())
        .subquery()
    )
    stmt = (
        select(
            current.c.id,
            current.c.stay_date,
            RoomType.name.label("room_type"),
            current.c.verdict,
            current.c.rate,
        )
        .join(RoomType, current.c.room_type_id == RoomType.id)
        .where(current.c.timing == FeedbackTiming.AFTER)
        .order_by(current.c.stay_date, RoomType.id)
    )
    return (await session.execute(stmt)).mappings().all()


async def tuning_feedback(
    session: AsyncSession, hotel_id: int
) -> Sequence[Mapping[str, Any]]:
    """The manager's rates a tune-up learns from, one row per room type and night.

    Takes each night's current (highest) version, given before or after the
    night, and keeps it if it has a rate (decision 0051). Rows carry id,
    stay_date, room_type_id, room_type (its name) and rate, oldest night first.
    """
    current = (
        select(Feedback)
        .where(Feedback.hotel_id == hotel_id)
        .distinct(Feedback.room_type_id, Feedback.stay_date)
        .order_by(Feedback.room_type_id, Feedback.stay_date, Feedback.version.desc())
        .subquery()
    )
    stmt = (
        select(
            current.c.id,
            current.c.stay_date,
            current.c.room_type_id,
            RoomType.name.label("room_type"),
            current.c.rate,
        )
        .join(RoomType, current.c.room_type_id == RoomType.id)
        .where(current.c.rate.is_not(None))
        .order_by(current.c.stay_date, RoomType.id)
    )
    return (await session.execute(stmt)).mappings().all()
