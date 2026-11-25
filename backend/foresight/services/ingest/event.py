import logging
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.city import City
from foresight.repository.upsert import Outcome
from foresight.services.adapters import predicthq
from foresight.services.adapters.predicthq import FetchResult, Market
from foresight.services.domain.event import save_event
from foresight.services.domain.window import Window

log = logging.getLogger(__name__)

RADIUS = "10km"


@dataclass(slots=True)
class EventReport:
    """Running totals of an events run; yielded after every saved month.

    Attributes:
        fetched (int): Records PredictHQ returned.
        rejected (int): Records that couldn't be normalized.
        outcomes (Counter[Outcome]): Events new, updated and unchanged.
        overflowed (list[tuple[date, date]]): Months PredictHQ cut short at
            the plan's result limit.
        empty (list[tuple[date, date]]): Months that came back with nothing,
            e.g. dates the plan doesn't cover.
    """

    fetched: int = 0
    rejected: int = 0
    outcomes: Counter[Outcome] = field(default_factory=Counter)
    overflowed: list[tuple[date, date]] = field(default_factory=list)
    empty: list[tuple[date, date]] = field(default_factory=list)


async def ingest_recent(
    session: AsyncSession,
    city: City,
    *,
    token: str,
    updated_since: datetime,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EventReport:
    """Saves upcoming events PredictHQ revised since a moment; does not commit.

    The routine refresh: only revised events, so a frequent run costs little
    quota.

    Args:
        session (AsyncSession): The database session.
        city (City): The market.
        token (str): The PredictHQ token.
        updated_since (datetime): Only events revised after this.
        transport (httpx.AsyncBaseTransport | None): A transport to use
            instead of the network, e.g. in a test.

    Returns:
        EventReport: What was fetched and saved.

    Raises:
        PredictHQLimitError: PredictHQ refused further requests.
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
    """Saves every event active in a window, newest month first.

    Never commits; the caller commits after each month, so a run cut short
    keeps every finished month. A failure raises out of the month it happened
    in, with that month unsaved.

    Args:
        session (AsyncSession): The database session.
        city (City): The market.
        window (Window): The nights to cover.
        token (str): The PredictHQ token.
        transport (httpx.AsyncBaseTransport | None): A transport to use
            instead of the network, e.g. in a test.

    Yields:
        tuple[EventReport, date, date]: The running report, and the month
            just saved.

    Raises:
        PredictHQLimitError: PredictHQ refused further requests.
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
            if not result.events:
                report.empty.append((first, last))
            await _save(session, city, result, report)
            yield report, first, last


async def _save(
    session: AsyncSession, city: City, result: FetchResult, report: EventReport
) -> None:
    """Saves one fetch's events and adds them to the report.

    Args:
        session (AsyncSession): The database session.
        city (City): The market.
        result (FetchResult): What PredictHQ returned.
        report (EventReport): The running totals, updated in place.
    """
    report.fetched += result.fetched
    report.rejected += len(result.rejected)
    for event in result.events:
        report.outcomes[await save_event(session, city.id, event)] += 1


def _market(city: City) -> Market:
    """Describes a city as PredictHQ searches it.

    Args:
        city (City): The city.

    Returns:
        Market: Its name and centre.
    """
    return Market(city=city.name, latitude=city.latitude, longitude=city.longitude)
