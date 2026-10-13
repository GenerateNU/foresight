from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import hotel as hotel_repo

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession


async def hotel_window(
    session: AsyncSession,
    hotel_id: int | None,
    start: date | None,
    end: date | None,
) -> tuple[date, date]:
    """Fill a missing `start` or `end` from the hotel's stay_date range.

    Every source aims at the same window; one whose API can't reach back that far
    just returns nothing for the early days, and the coverage report shows the gap.

    Raises:
        ValueError: If a date is missing and the hotel has no nights loaded (or
            no hotel was given), or if `start` is after `end`.
    """
    if start is None or end is None:
        loaded = (
            None
            if hotel_id is None
            else await hotel_repo.stay_date_range(session, hotel_id)
        )
        if loaded is None:
            raise ValueError(
                "no hotel nights loaded; give --hotel-id of a loaded hotel, "
                "or both --start and --end"
            )
        start = start or loaded[0]
        end = end or loaded[1]
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    return start, end
