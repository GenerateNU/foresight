"""PredictHQ events for a city, fetched and saved.

Two modes, chosen by whether the caller gave dates:

- `ingest_recent`: the routine refresh. Only events PredictHQ revised since a
  moment, so a frequent run costs little quota.
- `ingest_window`: a backfill. Every event active in the window, a month at a
  time, so a run cut short keeps every finished month.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from foresight.services.adapters import predicthq
from foresight.services.adapters.predicthq import FetchResult, Market
from foresight.services.domain.event import save_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import date, datetime

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City
    from foresight.repository.upsert import Outcome
    from foresight.services.ingest.window import Window

log = logging.getLogger(__name__)

RADIUS = "10km"


@dataclass(slots=True)
class EventReport:
    """Running totals; yielded after every saved chunk."""

    fetched: int = 0
    rejected: int = 0
    outcomes: Counter[Outcome] = field(default_factory=Counter)
    # Months PredictHQ truncated at the plan's result limit.
    overflowed: list[tuple[date, date]] = field(default_factory=list)


async def ingest_recent(
    session: AsyncSession,
    city: City,
    *,
    token: str,
    updated_since: datetime,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EventReport:
    """Save upcoming events PredictHQ revised since `updated_since`.

    Does not commit. Raises the adapter's errors.
    """
    async with predicthq.client(token, transport=transport) as http:
        result = await predicthq.fetch(
            http,
            predicthq.recent_params(
                _market(city), updated_since=updated_since, radius=RADIUS
            ),
            city=city.name,
        )
    report = EventReport()
    await _save(session, city, result, report)
    return report


async def ingest_window(
    session: AsyncSession,
    city: City,
    window: Window,
    *,
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[tuple[EventReport, date, date]]:
    """Save every event active in `window`, a month at a time.

    Yields the running report and the month just saved, so the caller can
    commit as it goes; never commits itself. A failure raises out of the
    month it happened in, with that month unsaved.
    """
    report = EventReport()
    market = _market(city)
    async with predicthq.client(token, transport=transport) as http:
        for first, last in window.months():
            result = await predicthq.fetch(
                http,
                predicthq.window_params(market, first, last, radius=RADIUS),
                city=city.name,
            )
            if result.overflowed:
                report.overflowed.append((first, last))
            await _save(session, city, result, report)
            yield report, first, last


async def _save(
    session: AsyncSession, city: City, result: FetchResult, report: EventReport
) -> None:
    report.fetched += result.fetched
    report.rejected += len(result.rejected)
    for event in result.events:
        report.outcomes[await save_event(session, city.id, event)] += 1


def _market(city: City) -> Market:
    return Market(city=city.name, latitude=city.latitude, longitude=city.longitude)
