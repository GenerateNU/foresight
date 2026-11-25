"""The date window an events backfill covers, from the optional `start` and
`end` given (decision 0087).

Giving either date makes the run a backfill. `end` defaults to today and
`start` to the hotel's first booked night. Every backfill walks newest month
first, so a source that runs out of credits has saved the most recent part,
and `resume_from` is always the `end` to send next.

Giving neither isn't a window; each signal has its own routine refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from foresight.repository import booking as booking_repo
from foresight.services.errors import InvalidRequestError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession


class InvalidWindowError(InvalidRequestError):
    """The requested date window can't be resolved."""


@dataclass(frozen=True, slots=True)
class Window:
    start: date
    end: date

    def as_params(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Window:
        return cls(
            date.fromisoformat(params["start"]), date.fromisoformat(params["end"])
        )

    def months(self) -> list[tuple[date, date]]:
        """Calendar-month pieces, inclusive, newest first."""
        pieces = []
        last = self.end
        while last >= self.start:
            first = max(last.replace(day=1), self.start)
            pieces.append((first, last))
            last = first - timedelta(days=1)
        return pieces


async def resolve_window(
    session: AsyncSession,
    hotel_id: int,
    start: date | None,
    end: date | None,
    *,
    today: date,
) -> Window:
    """`end` defaults to today, `start` to the hotel's first booked night.

    Only call with at least one date given.

    Raises:
        InvalidWindowError: `start` is needed and no bookings are loaded, or
            the window is empty.
    """
    end = end or today
    if start is None:
        loaded = await booking_repo.booked_night_range(session, hotel_id)
        if loaded is None:
            raise InvalidWindowError(
                "without a start the backfill goes back to the hotel's first "
                "booked night, and no bookings are loaded; give a start"
            )
        start = loaded[0]
    if start > end:
        raise InvalidWindowError(f"start {start} is after end {end}")
    return Window(start, end)
