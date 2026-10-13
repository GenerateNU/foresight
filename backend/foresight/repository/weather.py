from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from foresight.database.models.external import Weather
from foresight.repository import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("city", "weather_date", "is_forecast", "source")
_MEASURES = ("temp_max_c", "temp_min_c", "precip_mm", "wind_kph", "condition")


async def upsert_weather(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (city, weather_date, is_forecast, source)."""
    return await upsert_rows(
        session,
        cast("Table", Weather.__table__),
        constraint="uq_weather_city_date_kind_source",
        key=_KEY,
        mutable=_MEASURES,
        rows=rows,
    )
