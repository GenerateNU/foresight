"""Weather: daily forecasts and recorded actuals for a hotel's city."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository.signals import weather as weather_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.signals.weather import Weather


async def list_weather(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Weather], int]:
    """Forecast and recorded rows for the hotel's city, both returned."""
    hotel = await get_hotel(session, hotel_id)
    return await weather_repo.list_weather(
        session, city_id=hotel.city_id, start=start, end=end, limit=limit, offset=offset
    )
