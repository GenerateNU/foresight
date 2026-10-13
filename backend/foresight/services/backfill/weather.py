from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from foresight.ingest.weather import fetch_actuals
from foresight.repository import weather as weather_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.repository import Outcome


async def backfill_weather(
    session: AsyncSession,
    *,
    city: str,
    latitude: float,
    longitude: float,
    start: date,
    end: date,
) -> dict[Outcome, int]:
    """Fetch recorded weather for every day from `start` to `end` and save it.

    The archive rejects future dates, so `end` is clamped to today. Does not
    commit; the caller owns the transaction.
    """
    rows = fetch_actuals(
        city, latitude, longitude, "auto", start=start, end=min(end, date.today())
    )
    return await weather_repo.upsert_weather(session, rows)
