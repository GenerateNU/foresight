"""Data access for `competitor_rates`: what competing hotels charge per night."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from foresight.database.models.competitor_rate import CompetitorRate
from foresight.repository.upsert import Outcome, upsert_rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

_KEY = ("hotel_name", "city", "stay_date", "source")
_MEASURES = ("rate", "is_sold_out")


async def upsert_competitor_rates(
    session: AsyncSession, rows: Iterable[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Write rows keyed on (hotel_name, city, stay_date, source)."""
    return await upsert_rows(
        session,
        CompetitorRate,
        constraint="uq_competitor_rates_hotel_name_city_stay_date_source",
        key=_KEY,
        mutable=_MEASURES,
        rows=rows,
    )
