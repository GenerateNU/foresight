"""PredictHQ adapter: events near a hotel as NormalizedEvents. No DB writes.

One client for both the recent-revisions sync and the date-range backfill;
they differ only in query parameters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from foresight.database.enums import DatePrecision, EventCategory, EventStatus, Source
from foresight.services.adapters.normalize import (
    NormalizedEvent,
    coords_from_geojson,
    to_local_date,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

API_URL = "https://api.predicthq.com/v1/events/"
PAGE_LIMIT = 500
# PredictHQ's docs don't name the status for an exhausted plan; treat both.
_OUT_OF_CREDITS = frozenset({402, 403})
# The API returns only `active` unless asked; an unseen deletion would leave a
# cancelled event in the demand forecast indefinitely.
STATES = "active,predicted,deleted"

_STATUS = {
    "active": EventStatus.ACTIVE,
    "predicted": EventStatus.PROVISIONAL,
    "deleted": EventStatus.DELETED,
}


@dataclass(slots=True)
class Market:
    """Where to search: the hotel's city and the centre of the radius."""

    city: str
    latitude: float
    longitude: float


@dataclass(slots=True)
class Rejected:
    source_ref: str
    reason: str


@dataclass(slots=True)
class FetchResult:
    events: list[NormalizedEvent] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    overflowed: bool = False  # the plan truncated results

    @property
    def fetched(self) -> int:
        return len(self.events) + len(self.rejected)


class PredictHQLimitError(Exception):
    """PredictHQ refused further requests; the run should stop."""


class OutOfCreditsError(PredictHQLimitError):
    """The plan's quota or credits are used up."""


class RateLimitedError(PredictHQLimitError):
    """PredictHQ answered 429."""


def client(
    token: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """An authenticated client; close it with `async with`."""
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30.0,
        transport=transport,
    )


def recent_params(
    market: Market, *, updated_since: datetime, radius: str = "10km"
) -> dict[str, Any]:
    """Upcoming events near `market` revised upstream since `updated_since`."""
    return {
        "within": f"{radius}@{market.latitude},{market.longitude}",
        "updated.gte": updated_since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        # A day of slack so an event running tonight in a zone behind UTC stays in.
        "active.gte": (datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
        "state": STATES,
        "limit": PAGE_LIMIT,
        "sort": "updated",
    }


def window_params(
    market: Market, start: date, end: date, *, radius: str = "10km"
) -> dict[str, Any]:
    """Every event active from `start` to `end`, with a day of slack each side."""
    return {
        "within": f"{radius}@{market.latitude},{market.longitude}",
        "active.gte": (start - timedelta(days=1)).isoformat(),
        "active.lte": (end + timedelta(days=1)).isoformat(),
        "state": STATES,
        "limit": PAGE_LIMIT,
        "sort": "start",
    }


async def fetch(
    http: httpx.AsyncClient,
    params: dict[str, Any],
    *,
    city: str,
    into: FetchResult | None = None,
) -> FetchResult:
    """Every page of a query, normalized. Bad records are rejected, not raised.

    `city` is the hotel's market and becomes every event's city, so a suburb
    venue still shares a dedupe key with a news article naming the city. Pass
    `into` to accumulate several queries in one result: on a limit error it
    keeps every page fetched before the error.

    Raises:
        OutOfCreditsError: On a 402 or 403.
        RateLimitedError: On a 429.
        httpx.HTTPError: On any other failure.
    """
    result = into if into is not None else FetchResult()
    url: str | None = API_URL
    query: dict[str, Any] | None = params
    while url:
        body = await get_page(http, url, query)
        if body.get("overflow"):
            log.warning("PredictHQ overflow: plan limit truncated results")
            result.overflowed = True
        for raw in body.get("results", []):
            try:
                result.events.append(to_normalized(raw, city=city))
            except (KeyError, TypeError, ValueError) as exc:
                ref = str(raw.get("id", "?")) if isinstance(raw, dict) else "?"
                log.warning("rejected PredictHQ event %s: %s", ref, exc)
                result.rejected.append(Rejected(ref, rejection_reason(exc)))
        # `next` already carries every query parameter.
        url, query = body.get("next"), None
    return result


async def get_page(
    http: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    """GET one page. No retries: a failed job records where to resume."""
    response = await http.get(url, params=params)
    if response.status_code == 429:
        raise RateLimitedError(f"HTTP 429: {response.text[:300]}")
    if response.status_code in _OUT_OF_CREDITS:
        raise OutOfCreditsError(f"HTTP {response.status_code}: {response.text[:300]}")
    response.raise_for_status()
    return response.json()


def to_normalized(raw: Mapping[str, Any], *, city: str) -> NormalizedEvent:
    start = _parse_instant(raw["start"])
    end = _parse_instant(raw["end"]) if raw.get("end") else start
    timezone = raw.get("timezone")
    latitude, longitude = coords_from_geojson(raw.get("location"))

    return NormalizedEvent(
        source=Source.PREDICTHQ,
        source_ref=raw["id"],
        title=raw["title"],
        city=city,
        start_local_date=to_local_date(start, timezone),
        end_local_date=to_local_date(end, timezone),
        timezone=timezone or "UTC",
        category=_category(raw.get("category")),
        date_precision=DatePrecision.DAY,
        status=_STATUS[raw["state"]],
        confidence=1.0,
        venue=_venue(raw.get("entities") or []),
        country=raw.get("country"),
        latitude=latitude,
        longitude=longitude,
        start_at_utc=start,
        end_at_utc=end,
        expected_attendance=raw.get("phq_attendance"),
        impact_rank=raw.get("rank"),
        local_rank=raw.get("local_rank"),
        source_updated_at=_parse_instant(raw["updated"])
        if raw.get("updated")
        else None,
        payload=dict(raw),
    )


def _parse_instant(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _category(value: str | None) -> EventCategory:
    try:
        return EventCategory(value)
    except ValueError:
        return EventCategory.UNKNOWN


def _venue(entities: list[Mapping[str, Any]]) -> str | None:
    return next((e.get("name") for e in entities if e.get("type") == "venue"), None)


def rejection_reason(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return f"missing field {exc.args[0]!r}"
    return str(exc)
