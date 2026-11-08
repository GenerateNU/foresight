"""The manager's feedback on a night's rate, before or after the night.

Feedback is only ever added: changing it adds the next version for that room
type and night, and the highest version is the current one (decision 0043).
The manager sends the rate they chose; whether ours was too high, too low or
about right is worked out from it (decision 0050).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.database.enums import FeedbackTiming, FeedbackVerdict
from foresight.repository import feedback as feedback_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain.city import local_today
from foresight.services.domain.hotel import get_hotel, get_room_type
from foresight.services.errors import ConflictError, InvalidRequestError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.enums import FeedbackReasonTag
    from foresight.database.models.feedback import Feedback

MAX_NIGHTS = 366


def verdict_for(rate: Decimal, recommended: Decimal) -> FeedbackVerdict:
    """How the manager's rate compares with ours: if they charge more, ours
    was too low; if less, too high; the same to the cent, about right."""
    if rate > recommended:
        return FeedbackVerdict.TOO_LOW
    if rate < recommended:
        return FeedbackVerdict.TOO_HIGH
    return FeedbackVerdict.ABOUT_RIGHT


async def add_feedback(
    session: AsyncSession,
    hotel_id: int,
    *,
    room_type_id: int,
    stay_date: date,
    rate: Decimal,
    reason_tags: list[FeedbackReasonTag],
    reason_text: str | None,
    snapshot_id: int,
    user_id: int | None = None,
) -> Feedback:
    """Save the next version of the feedback for this room type and night.

    `rate` is what the manager chose to charge, and `snapshot_id` the
    recommendation they saw; the verdict is worked out by comparing the two.
    Whether it came before or after the night is set here, from the stay date
    in the hotel's timezone: a night before today is over; today and later are
    still ahead. A repeated tag is kept once.

    Raises:
        NotFoundError: Unknown hotel, a room type that isn't the hotel's, or a
            snapshot that isn't the hotel's.
        InvalidRequestError: The snapshot is for another room type or night.
        ConflictError: Another version was saved at the same moment.
    """
    hotel = await get_hotel(session, hotel_id)
    room_type = await get_room_type(session, room_type_id)
    if room_type.hotel_id != hotel.id:
        raise NotFoundError("Room type", room_type_id)

    snapshot = await snapshot_repo.get_snapshot(session, snapshot_id)
    if snapshot is None or snapshot.hotel_id != hotel.id:
        raise NotFoundError("Snapshot", snapshot_id)
    if snapshot.room_type_id != room_type.id or snapshot.stay_date != stay_date:
        raise InvalidRequestError(
            f"snapshot {snapshot_id} is for another room type or night"
        )

    timing = (
        FeedbackTiming.AFTER
        if stay_date < local_today(hotel.city)
        else FeedbackTiming.BEFORE
    )
    feedback = await feedback_repo.create_feedback(
        session,
        hotel_id=hotel.id,
        room_type_id=room_type.id,
        stay_date=stay_date,
        snapshot_id=snapshot_id,
        user_id=user_id,
        verdict=verdict_for(rate, snapshot.rate),
        rate=rate,
        reason_tags=list(dict.fromkeys(reason_tags)),
        reason_text=reason_text,
        timing=timing,
    )
    if feedback is None:
        raise ConflictError(
            f"Feedback for {stay_date} was changed at the same moment; send it again"
        )
    return feedback


async def list_feedback(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date,
    end: date,
    room_type_id: int | None = None,
    include_history: bool = False,
) -> Sequence[Feedback]:
    """The current feedback for each night in [start, end], oldest night first;
    with `include_history`, every version.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: `end` before `start`, or more than `MAX_NIGHTS`.
    """
    if end < start:
        raise InvalidRequestError("end must not be before start")
    if (end - start).days + 1 > MAX_NIGHTS:
        raise InvalidRequestError(f"at most {MAX_NIGHTS} nights at a time")
    await get_hotel(session, hotel_id)
    return await feedback_repo.list_feedback(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_id=room_type_id,
        include_history=include_history,
    )
