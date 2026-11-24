"""Data access for `feedback`: the manager's view of a night, one row per version."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, func, select
from sqlalchemy.dialects.postgresql import insert

from foresight.database.enums import FeedbackReasonTag
from foresight.database.models.feedback import Feedback
from foresight.database.models.recommendation import RecommendationSnapshot

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession


async def create_feedback(
    session: AsyncSession,
    *,
    hotel_id: int,
    room_type_id: int,
    stay_date: date,
    snapshot_id: int | None,
    user_id: int | None,
    rate: Decimal | None,
    reason_tags: list[FeedbackReasonTag],
    reason_text: str | None,
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
            rate=rate,
            reason_tags=reason_tags,
            reason_text=reason_text,
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


async def tuning_feedback(
    session: AsyncSession,
    room_type_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
) -> Sequence[Mapping[str, Any]]:
    """The manager's rates a tune-up or a full retrain learns from.

    One row per room type and night. Takes each night's current (highest)
    version, given before or after the night, and keeps it if it has a rate
    (decisions 0069 and 0071) and isn't
    tagged ONE_OFF (decision 0070). Rows carry id, stay_date, rate (nett where
    the version was, decision 0076) and given_at: when the manager set the rate
    (decision 0084). Oldest night first.
    Only the one room type; `start` and `end` limit the nights.
    """
    current = select(Feedback).where(Feedback.room_type_id == room_type_id)
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
            current.c.rate,
            current.c.created_at.label("given_at"),
        )
        .where(
            current.c.rate.is_not(None),
            ~current.c.reason_tags.contains([FeedbackReasonTag.ONE_OFF]),
        )
        .order_by(current.c.stay_date)
    )
    return (await session.execute(stmt)).mappings().all()


async def one_off_nights(
    session: AsyncSession,
    room_type_id: int,
    *,
    start: date | None,
    end: date | None,
) -> Sequence[Mapping[str, Any]]:
    """The nights the manager marked as one-off, which training leaves out.

    A room type's night is one-off when its current (highest) version of
    feedback carries the ONE_OFF tag, given before or after the night
    (decision 0070). Only the one room type. Rows carry stay_date.
    """
    current = select(Feedback).where(Feedback.room_type_id == room_type_id)
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
        select(current.c.stay_date)
        .where(current.c.reason_tags.contains([FeedbackReasonTag.ONE_OFF]))
        .order_by(current.c.stay_date)
    )
    return (await session.execute(stmt)).mappings().all()


async def manager_rates(
    session: AsyncSession, room_type_id: int, *, start: date, end: date
) -> dict[date, Decimal]:
    """The rate the manager has set for each night in [start, end], if any.

    Takes each night's current (highest) version and keeps it if it has a rate,
    so a night whose latest version has no rate has none (decision 0071).
    """
    current = (
        select(Feedback.stay_date, Feedback.rate)
        .where(
            Feedback.room_type_id == room_type_id,
            Feedback.stay_date >= start,
            Feedback.stay_date <= end,
        )
        .distinct(Feedback.stay_date)
        .order_by(Feedback.stay_date, Feedback.version.desc())
        .subquery()
    )
    rows = await session.execute(
        select(current.c.stay_date, current.c.rate).where(current.c.rate.is_not(None))
    )
    return {day: rate for day, rate in rows}


async def alignment_by_week(
    session: AsyncSession, hotel_id: int
) -> Sequence[Mapping[str, Any]]:
    """How far the manager's rates were from the rates they were shown, by week.

    Every version of feedback that has a rate and still has its snapshot counts
    once, in the week (Monday, UTC) it was given. Rows carry week, nights,
    mean_gap (manager minus model, so positive means the model priced low) and
    mean_abs_gap, oldest week first (decision 0071).
    """
    gap = Feedback.rate - RecommendationSnapshot.rate
    week = func.date_trunc("week", Feedback.created_at)
    stmt = (
        select(
            func.cast(week, Date).label("week"),
            func.count().label("nights"),
            func.avg(gap).label("mean_gap"),
            func.avg(func.abs(gap)).label("mean_abs_gap"),
        )
        .join(RecommendationSnapshot, Feedback.snapshot_id == RecommendationSnapshot.id)
        .where(Feedback.hotel_id == hotel_id, Feedback.rate.is_not(None))
        .group_by(week)
        .order_by(week)
    )
    return (await session.execute(stmt)).mappings().all()
