from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.repository import booking as booking_repo
from foresight.services.errors import InvalidRequestError


class InvalidWindowError(InvalidRequestError):
    """The requested date window can't be resolved."""


@dataclass(frozen=True, slots=True)
class Window:
    """The nights an events backfill covers, inclusive.

    Every backfill walks newest month first, so a source that runs out of
    credits has saved the most recent part, and `resume_from` is always the
    `end` to send next.

    Attributes:
        start (date): First night.
        end (date): Last night.
    """

    start: date
    end: date

    def as_params(self) -> dict[str, str]:
        """Stores the window on a job.

        Returns:
            dict[str, str]: `start` and `end` as ISO dates.
        """
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Window":
        """Reads a window stored by `as_params`.

        Args:
            params (Mapping[str, Any]): A job's params.

        Returns:
            Window: The window.
        """
        return cls(
            date.fromisoformat(params["start"]), date.fromisoformat(params["end"])
        )

    def months(self) -> list[tuple[date, date]]:
        """Splits the window into calendar months, newest first.

        Returns:
            list[tuple[date, date]]: Each month's first and last night in the
                window, inclusive.
        """
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
    """Fills in the dates a backfill request left out.

    Giving either date makes a run a backfill; only call with at least one.
    Giving neither isn't a window: each signal has its own routine refresh.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date | None): First night; None for the first booked night.
        end (date | None): Last night; None for today.
        today (date): Today, in the hotel's city.

    Returns:
        Window: The window.

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
