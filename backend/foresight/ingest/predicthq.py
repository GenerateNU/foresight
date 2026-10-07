"""PredictHQ adapter: events near a hotel as NormalizedEvents. No DB writes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from foresight.ingest.normalize import (
    DatePrecision,
    EventCategory,
    EventStatus,
    NormalizedEvent,
    Source,
    coords_from_geojson,
    to_local_date,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

API_URL = "https://api.predicthq.com/v1/events/"
PAGE_LIMIT = 500
# The API returns only `active` unless asked; an unseen deletion would leave a
# cancelled event in the demand forecast indefinitely.
STATES = "active,predicted,deleted"

_STATUS = {
    "active": EventStatus.ACTIVE,
    "predicted": EventStatus.PROVISIONAL,
    "deleted": EventStatus.DELETED,
}


@dataclass(slots=True)
class Rejected:
    source_ref: str
    reason: str


@dataclass(slots=True)
class FetchResult:
    events: list[NormalizedEvent] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)

    @property
    def fetched(self) -> int:
        return len(self.events) + len(self.rejected)


async def fetch_events(
    *,
    token: str,
    latitude: float,
    longitude: float,
    city: str,
    updated_since: datetime,
    radius: str = "10km",
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    """Events within `radius` of a point, revised upstream since `updated_since`.

    `city` is the hotel's market and becomes every event's city, so a suburb
    venue still shares a dedupe key with a news article naming the city.
    """
    params = {
        "within": f"{radius}@{latitude},{longitude}",
        "updated.gte": updated_since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        # A day of slack so an event running tonight in a zone behind UTC stays in.
        "active.gte": (datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
        "state": STATES,
        "limit": PAGE_LIMIT,
        "sort": "updated",
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    result = FetchResult()

    async with httpx.AsyncClient(
        headers=headers, timeout=30.0, transport=transport
    ) as client:
        url: str | None = API_URL
        query: dict[str, Any] | None = params
        while url:
            response = await client.get(url, params=query)
            response.raise_for_status()
            body = response.json()
            if body.get("overflow"):
                log.warning("PredictHQ result overflow: plan limit truncated results")

            for raw in body.get("results", []):
                try:
                    result.events.append(to_normalized(raw, city=city))
                except (KeyError, TypeError, ValueError) as exc:
                    ref = str(raw.get("id", "?")) if isinstance(raw, dict) else "?"
                    log.warning("rejected PredictHQ event %s: %s", ref, exc)
                    result.rejected.append(Rejected(ref, _reason(exc)))

            # `next` already carries every query parameter.
            url, query = body.get("next"), None

    return result


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


def _reason(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return f"missing field {exc.args[0]!r}"
    return str(exc)
