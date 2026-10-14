"""The date window an ingest covers, from the optional `start` and `end` given.

Giving any date makes the run a backfill over a window:

- start and end: that window.
- start only: start to today.
- end only: backwards from end to the hotel's first loaded night, newest
  first, so a source that runs out of credits has saved the most recent part.

Giving neither isn't a window; each signal has its own routine refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from foresight.repository import hotel as hotel_repo
from foresight.services.errors import InvalidRequestError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.ext.asyncio import AsyncSession


class InvalidWindowError(InvalidRequestError):
    """The requested date window can't be resolved."""


@dataclass(frozen=True, slots=True)
class Window:
    start: date
    end: date
    backwards: bool = False  # walk newest first

    def as_params(self) -> dict[str, str | bool]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "backwards": self.backwards,
        }

    @classmethod
    def from_params(cls, params: dict) -> Window:
        return cls(
            date.fromisoformat(params["start"]),
            date.fromisoformat(params["end"]),
            params.get("backwards", False),
        )

    def months(self) -> Iterator[tuple[date, date]]:
        """Calendar-month pieces, inclusive, in walking order."""
        return self._pieces(
            lambda d: (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        )

    def years(self) -> Iterator[tuple[date, date]]:
        """Calendar-year pieces, inclusive, in walking order."""
        return self._pieces(lambda d: date(d.year + 1, 1, 1))

    def clip(self, start: date, end: date) -> Window | None:
        """The part of this window inside `start`..`end`, if any."""
        first, last = max(self.start, start), min(self.end, end)
        return Window(first, last, self.backwards) if first <= last else None

    def _pieces(
        self, next_boundary: Callable[[date], date]
    ) -> Iterator[tuple[date, date]]:
        pieces = []
        first = self.start
        while first <= self.end:
            last = min(next_boundary(first) - timedelta(days=1), self.end)
            pieces.append((first, last))
            first = last + timedelta(days=1)
        return reversed(pieces) if self.backwards else iter(pieces)

    def resume_point(self, first: date, last: date) -> date:
        """The `start` (forwards) or `end` (backwards) to pass to pick up at
        the piece `first`..`last`."""
        return last if self.backwards else first


async def resolve_window(
    session: AsyncSession,
    hotel_id: int,
    start: date | None,
    end: date | None,
    *,
    today: date,
) -> Window:
    """Raises InvalidWindowError if the window is empty or can't be resolved.

    Only call with at least one date given.
    """
    if start is not None and end is None:
        end = today
    elif start is None and end is not None:
        loaded = await hotel_repo.stay_date_range(session, hotel_id)
        if loaded is None:
            raise InvalidWindowError(
                "end alone walks back to the hotel's first loaded night, and "
                "none are loaded; give a start too"
            )
        if loaded[0] > end:
            raise InvalidWindowError(
                f"end {end} is before the hotel's first loaded night {loaded[0]}"
            )
        return Window(loaded[0], end, backwards=True)
    assert start is not None and end is not None
    if start > end:
        raise InvalidWindowError(f"start {start} is after end {end}")
    return Window(start, end)
