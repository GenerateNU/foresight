from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from foresight.repository.upsert import Outcome
from foresight.services.event import save_event
from foresight.services.ingest import predicthq
from foresight.services.ingest.predicthq import (
    FetchResult,
    Market,
    PredictHQLimitError,
    Rejected,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.services.ingest.http import Sleep

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BackfillReport:
    market: Market
    start: date
    end: date
    chunks_total: int
    chunks_done: int = 0
    fetched: int = 0
    outcomes: Counter[Outcome] = field(default_factory=Counter)
    rejected: list[Rejected] = field(default_factory=list)
    overflow_chunks: list[tuple[date, date]] = field(default_factory=list)
    stopped: str | None = None
    resume_from: date | None = None
    dry_run: bool = False

    def summary(self) -> str:
        """One line of counts for the run."""
        counts = (
            "(dry run, nothing written)"
            if self.dry_run
            else " ".join(f"{o.value}={self.outcomes[o]}" for o in Outcome)
        )
        return (
            f"{self.market.city} {self.start}..{self.end} "
            f"chunks={self.chunks_done}/{self.chunks_total} "
            f"fetched={self.fetched} {counts} rejected={len(self.rejected)}"
        )


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split a date range into calendar-month pieces, oldest first, inclusive."""
    chunks = []
    first = start
    while first <= end:
        next_month = (first.replace(day=1) + timedelta(days=32)).replace(day=1)
        last = min(next_month - timedelta(days=1), end)
        chunks.append((first, last))
        first = last + timedelta(days=1)
    return chunks


async def backfill(
    session: AsyncSession | None,
    market: Market,
    start: date,
    end: date,
    *,
    token: str,
    radius: str = "10km",
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Sleep = asyncio.sleep,
) -> AsyncIterator[BackfillReport]:
    """Fetch and save every event active from `start` to `end`, a month at a time.

    Yields the report after each month so the caller can commit as it goes;
    never commits itself. A PredictHQ limit ends the run: the report is yielded
    once more with `stopped` and `resume_from` set, and events from pages
    fetched before the limit are still saved.

    `session=None` is a dry run: fetch and count, write nothing.
    """
    chunks = month_chunks(start, end)
    report = BackfillReport(
        market=market,
        start=start,
        end=end,
        chunks_total=len(chunks),
        dry_run=session is None,
    )
    async with predicthq.client(token, transport=transport) as http:
        for first, last in chunks:
            fetched = FetchResult()
            stopped: str | None = None
            try:
                await predicthq.fetch(
                    http,
                    predicthq.window_params(market, first, last, radius=radius),
                    city=market.city,
                    sleep=sleep,
                    into=fetched,
                )
            except PredictHQLimitError as exc:
                stopped = str(exc)

            report.fetched += fetched.fetched
            report.rejected += fetched.rejected
            if fetched.overflowed:
                report.overflow_chunks.append((first, last))
            if session is not None:
                for event in fetched.events:
                    report.outcomes[await save_event(session, event)] += 1

            if stopped is not None:
                report.stopped, report.resume_from = stopped, first
                yield report
                return
            report.chunks_done += 1
            yield report
