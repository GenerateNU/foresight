from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import FeedbackReasonTag
from foresight.database.models.feedback import Feedback


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
    """Adds the next version of a night's feedback; never updates a row.

    The version is worked out in the insert itself.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        room_type_id (int): The room type.
        stay_date (date): The night.
        snapshot_id (int | None): The recommendation the manager saw.
        user_id (int | None): Who gave it.
        rate (Decimal | None): The rate the manager chose, before VAT.
        reason_tags (list[FeedbackReasonTag]): Why, from a fixed list.
        reason_text (str | None): Why, in the manager's words.

    Returns:
        Feedback | None: The new version, or None if another version with the
            same number was added at the same moment.
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
    include_history: bool,
) -> Sequence[Feedback]:
    """Lists the hotel's feedback for nights in a window, oldest night first.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        include_history (bool): Also return earlier versions, oldest first;
            otherwise only each night's current version.

    Returns:
        Sequence[Feedback]: The feedback rows.
    """
    stmt = select(Feedback).where(
        Feedback.hotel_id == hotel_id, Feedback.stay_date.between(start, end)
    )
    if include_history:
        stmt = stmt.order_by(
            Feedback.stay_date, Feedback.room_type_id, Feedback.version
        )
    else:
        stmt = _current_versions(stmt)
    return (await session.scalars(stmt)).all()


async def current_feedback(
    session: AsyncSession,
    room_type_id: int,
    *,
    start: date | None,
    end: date | None,
) -> Sequence[Feedback]:
    """Lists the current version of each night's feedback for a room type.

    Args:
        session (AsyncSession): The database session.
        room_type_id (int): The room type.
        start (date | None): First night, inclusive; None for no limit.
        end (date | None): Last night, inclusive; None for no limit.

    Returns:
        Sequence[Feedback]: One row per night, oldest night first.
    """
    stmt = select(Feedback).where(Feedback.room_type_id == room_type_id)
    if start is not None:
        stmt = stmt.where(Feedback.stay_date >= start)
    if end is not None:
        stmt = stmt.where(Feedback.stay_date <= end)
    return (await session.scalars(_current_versions(stmt))).all()


def _current_versions(stmt: Select[tuple[Feedback]]) -> Select[tuple[Feedback]]:
    """Keeps only the highest version of each room type's night.

    Args:
        stmt (Select[tuple[Feedback]]): A query over feedback.

    Returns:
        Select[tuple[Feedback]]: The query, keeping each night's current
            version, oldest night first.
    """
    return stmt.distinct(Feedback.stay_date, Feedback.room_type_id).order_by(
        Feedback.stay_date, Feedback.room_type_id, Feedback.version.desc()
    )
