"""Weather: daily forecasts and recorded actuals per city."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import weather as weather_repo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.weather import Weather


async def list_weather(
    session: AsyncSession,
    *,
    city: str,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Weather], int]:
    """Forecast and recorded rows for `city`, both returned."""
    return await weather_repo.list_weather(
        session, city=city, start=start, end=end, limit=limit, offset=offset
    )
