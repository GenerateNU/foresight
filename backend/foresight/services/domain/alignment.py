"""Is the model getting closer to how the manager prices? (decision 0071)

Each piece of feedback with a rate is compared with the recommendation the
manager saw when they gave it. If tune-ups and retrains are working, the gap
shrinks week over week.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from foresight.repository import feedback as feedback_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class WeekAlignment:
    week: date  # Monday of the week the feedback was given
    nights: int  # pieces of feedback with a rate that week
    mean_gap: Decimal  # manager minus model; positive means the model priced low
    mean_abs_gap: Decimal  # the size of the gap, whichever way


async def get_alignment(session: AsyncSession, hotel_id: int) -> list[WeekAlignment]:
    """The gap between the manager's rates and the model's, by week, oldest first.

    Raises:
        NotFoundError: Unknown hotel.
    """
    hotel = await get_hotel(session, hotel_id)
    rows = await feedback_repo.alignment_by_week(session, hotel.id)
    return [
        WeekAlignment(
            r["week"],
            r["nights"],
            round(r["mean_gap"], 2),
            round(r["mean_abs_gap"], 2),
        )
        for r in rows
    ]
