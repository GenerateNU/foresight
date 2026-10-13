from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from foresight.ingest.predicthq import (
    API_URL,
    PAGE_LIMIT,
    STATES,
    Rejected,
    rejection_reason,
    to_normalized,
)
from foresight.repository import Outcome
from foresight.repository.events import upsert_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.ingest.run import Market

log = logging.getLogger("foresight.ingest")

MAX_RETRIES = 5
BACKOFF_SECONDS = 2.0
# PredictHQ's docs don't name the status for an exhausted plan; treat both.
_OUT_OF_CREDITS = {402, 403}


class PredictHQLimitError(Exception):
    """PredictHQ refused further requests; the run should stop."""


class OutOfCreditsError(PredictHQLimitError):
    """The plan's quota or credits are used up."""


class RetriesExhaustedError(PredictHQLimitError):
    """Still rate limited or failing after every retry."""


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
    """Split a date range into calendar-month pieces, oldest first.

    Args:
        start (date): First day, inclusive.
        end (date): Last day, inclusive.

    Returns:
        list[tuple[date, date]]: Inclusive (first, last) day of each piece.
    """
    chunks = []
    first = start
    while first <= end:
        next_month = (first.replace(day=1) + timedelta(days=32)).replace(day=1)
        last = min(next_month - timedelta(days=1), end)
        chunks.append((first, last))
        first = last + timedelta(days=1)
    return chunks


def chunk_params(market: Market, start: date, end: date, radius: str) -> dict[str, Any]:
    """Query for every event active within a chunk, with a day of slack each side.

    Args:
        market (Market): Centre of the search.
        start (date): First day of the chunk.
        end (date): Last day of the chunk.
        radius (str): Search radius, e.g. "10km".

    Returns:
        dict[str, Any]: PredictHQ query parameters.
    """
    return {
        "within": f"{radius}@{market.latitude},{market.longitude}",
        "active.gte": (start - timedelta(days=1)).isoformat(),
        "active.lte": (end + timedelta(days=1)).isoformat(),
        "state": STATES,
        "limit": PAGE_LIMIT,
        "sort": "start",
    }


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    """GET one page, waiting and retrying only on 429, 5xx or network errors.

    Args:
        client (httpx.AsyncClient): Authenticated client.
        url (str): Page URL.
        params (dict[str, Any] | None): Query, or None for a `next` link.
        sleep (Callable[[float], Awaitable[None]]): Waits between retries.

    Returns:
        dict[str, Any]: The page's JSON body.

    Raises:
        OutOfCreditsError: On a 402 or 403.
        RetriesExhaustedError: If every retry still fails.
        httpx.HTTPStatusError: On any other 4xx.
    """
    problem, delay = "", 0.0
    for attempt in range(MAX_RETRIES + 1):
        if attempt:
            await sleep(delay)
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError as exc:
            problem = f"network error: {exc}"
            delay = BACKOFF_SECONDS * 2**attempt
            continue

        status = response.status_code
        if status in _OUT_OF_CREDITS:
            raise OutOfCreditsError(f"HTTP {status}: {response.text[:300]}")
        if status == 429 or status >= 500:
            problem = f"HTTP {status}"
            delay = _retry_after(response) or BACKOFF_SECONDS * 2**attempt
            log.warning("PredictHQ %s, retrying in %.0fs", problem, delay)
            continue
        response.raise_for_status()
        return response.json()

    raise RetriesExhaustedError(f"{problem} after {MAX_RETRIES} retries")


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


async def backfill(
    session: AsyncSession | None,
    market: Market,
    start: date,
    end: date,
    *,
    token: str,
    radius: str = "10km",
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[BackfillReport]:
    """Fetch and upsert every event active from `start` to `end`, a month at a time.

    Yields the report after each month so the caller can commit as it goes;
    never commits itself. A PredictHQ limit ends the run: the report is yielded
    once more with `stopped` and `resume_from` set.

    Args:
        session (AsyncSession | None): Where to write; None for a dry run.
        market (Market): City and centre of the search.
        start (date): First day, inclusive.
        end (date): Last day, inclusive.
        token (str): PredictHQ access token.
        radius (str): Search radius, e.g. "10km".
        transport (httpx.AsyncBaseTransport | None): Test transport.
        sleep (Callable[[float], Awaitable[None]]): Waits between retries.

    Yields:
        BackfillReport: Running counts after each month, or the stopped run.
    """
    chunks = month_chunks(start, end)
    report = BackfillReport(
        market=market,
        start=start,
        end=end,
        chunks_total=len(chunks),
        dry_run=session is None,
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async with httpx.AsyncClient(
        headers=headers, timeout=30.0, transport=transport
    ) as client:
        for first, last in chunks:
            try:
                await _backfill_chunk(
                    client, session, report, first, last, radius, sleep
                )
            except PredictHQLimitError as exc:
                report.stopped = str(exc)
                report.resume_from = first
                yield report
                return
            report.chunks_done += 1
            yield report


async def _backfill_chunk(
    client: httpx.AsyncClient,
    session: AsyncSession | None,
    report: BackfillReport,
    first: date,
    last: date,
    radius: str,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    url: str | None = API_URL
    query: dict[str, Any] | None = chunk_params(report.market, first, last, radius)
    while url:
        body = await _get(client, url, query, sleep=sleep)
        if body.get("overflow") and (first, last) not in report.overflow_chunks:
            log.warning(
                "PredictHQ overflow for %s..%s: plan truncated results", first, last
            )
            report.overflow_chunks.append((first, last))

        for raw in body.get("results", []):
            report.fetched += 1
            try:
                event = to_normalized(raw, city=report.market.city)
            except (KeyError, TypeError, ValueError) as exc:
                ref = str(raw.get("id", "?")) if isinstance(raw, dict) else "?"
                log.warning("rejected PredictHQ event %s: %s", ref, exc)
                report.rejected.append(Rejected(ref, rejection_reason(exc)))
                continue
            if session is not None:
                report.outcomes[await upsert_event(session, event)] += 1

        # `next` already carries every query parameter.
        url, query = body.get("next"), None
