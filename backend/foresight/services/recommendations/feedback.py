from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import FeedbackReasonTag
from foresight.database.models.feedback import Feedback
from foresight.repository import feedback as feedback_repo
from foresight.repository import recommendation as recommendation_repo
from foresight.services.errors import ConflictError, InvalidRequestError, NotFoundError
from foresight.services.hotels.hotel import get_hotel

MAX_NIGHTS = 366


async def add_feedback(
    session: AsyncSession,
    hotel_id: int,
    *,
    stay_date: date,
    rate: Decimal,
    reason_tags: list[FeedbackReasonTag],
    reason_text: str | None,
    snapshot_id: int,
    user_id: int | None = None,
) -> Feedback:
    """Saves the next version of the feedback for a night.

    Feedback is only ever added: changing it adds the next version, and the
    highest version is the current one. The manager sends the rate they
    chose; whether ours was too high or too low is worked out from it. The
    room type is the snapshot's: the one the model prices.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        stay_date (date): The night.
        rate (Decimal): The rate the manager chose, before VAT like the
            recommendation.
        reason_tags (list[FeedbackReasonTag]): Why; a repeated tag is kept
            once.
        reason_text (str | None): Why, in their words.
        snapshot_id (int): The recommendation they saw, for the same night.
        user_id (int | None): Who gave it.

    Returns:
        Feedback: The new version.

    Raises:
        NotFoundError: Unknown hotel, or a snapshot that isn't the hotel's.
        InvalidRequestError: The snapshot is for another night.
        ConflictError: Another version was saved at the same moment.
    """
    hotel = await get_hotel(session, hotel_id)
    snapshot = await recommendation_repo.get_snapshot(session, snapshot_id)
    if snapshot is None or snapshot.hotel_id != hotel.id:
        raise NotFoundError("Snapshot", snapshot_id)
    if snapshot.stay_date != stay_date:
        raise InvalidRequestError(f"snapshot {snapshot_id} is for another night")
    feedback = await feedback_repo.create_feedback(
        session,
        hotel_id=hotel.id,
        room_type_id=snapshot.room_type_id,
        stay_date=stay_date,
        snapshot_id=snapshot_id,
        user_id=user_id,
        rate=rate,
        reason_tags=list(dict.fromkeys(reason_tags)),
        reason_text=reason_text,
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
    include_history: bool = False,
) -> Sequence[Feedback]:
    """Lists the current feedback for each night in a range.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        include_history (bool): Every version, not just the current one.

    Returns:
        Sequence[Feedback]: Oldest night first.

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
        include_history=include_history,
    )


@dataclass(frozen=True, slots=True)
class CurrentFeedback:
    """The current version of each night's feedback for one room type.

    Attributes:
        rows (list[Feedback]): One row per night, oldest night first.
    """

    rows: list[Feedback]

    @property
    def one_off_nights(self) -> set[date]:
        """The nights the manager tagged one-off, which teach the model nothing.

        Returns:
            set[date]: The one-off nights.
        """
        return {
            f.stay_date for f in self.rows if FeedbackReasonTag.ONE_OFF in f.reason_tags
        }

    @property
    def manager_rates(self) -> dict[date, Decimal]:
        """The rate the manager set for each night that has one.

        Returns:
            dict[date, Decimal]: Each night's rate.
        """
        return {f.stay_date: f.rate for f in self.rows if f.rate is not None}

    @property
    def training_rates(self) -> list[Feedback]:
        """The rates a retrain or a tune-up learns from.

        Every night with a rate that isn't one-off.

        Returns:
            list[Feedback]: The feedback rows, oldest night first.
        """
        one_off = self.one_off_nights
        return [
            f for f in self.rows if f.rate is not None and f.stay_date not in one_off
        ]


async def current_feedback(
    session: AsyncSession,
    room_type_id: int | None,
    *,
    start: date | None = None,
    end: date | None = None,
) -> CurrentFeedback:
    """Loads the current version of each night's feedback for a room type.

    Args:
        session (AsyncSession): The database session.
        room_type_id (int | None): The room type; None, before training has
            created it, gives no feedback.
        start (date | None): First night, inclusive; None for no limit.
        end (date | None): Last night, inclusive; None for no limit.

    Returns:
        CurrentFeedback: The current feedback.
    """
    if room_type_id is None:
        return CurrentFeedback([])
    rows = await feedback_repo.current_feedback(
        session, room_type_id, start=start, end=end
    )
    return CurrentFeedback(list(rows))
