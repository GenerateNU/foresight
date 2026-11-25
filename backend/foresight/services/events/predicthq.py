import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from foresight.database.enums import DatePrecision, EventCategory, EventStatus, Source
from foresight.services.events.normalize import (
    NormalizedEvent,
    coords_from_geojson,
    to_local_date,
)

log = logging.getLogger(__name__)

API_URL = "https://api.predicthq.com/v1/events/"
PAGE_LIMIT = 500
STATES = "active,predicted,deleted"
_OUT_OF_CREDITS = frozenset({402, 403})
_STATUS = {
    "active": EventStatus.ACTIVE,
    "predicted": EventStatus.PROVISIONAL,
    "deleted": EventStatus.DELETED,
}


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Results                          │
#          ╰──────────────────────────────────────────────────────────╯


@dataclass(slots=True)
class Market:
    """Where to search: the hotel's city and the centre of the radius.

    Attributes:
        city (str): The city's name, given to every event found.
        latitude (float): The centre of the search.
        longitude (float): The centre of the search.
    """

    city: str
    latitude: float
    longitude: float


@dataclass(slots=True)
class Rejected:
    """A record that couldn't be normalized.

    Attributes:
        source_ref (str): PredictHQ's id for it.
        reason (str): Why it was rejected.
    """

    source_ref: str
    reason: str


@dataclass(slots=True)
class FetchResult:
    """What a query returned, across every page.

    Attributes:
        events (list[NormalizedEvent]): The records normalized.
        rejected (list[Rejected]): The records that couldn't be.
        overflowed (bool): Whether the plan truncated the results.
    """

    events: list[NormalizedEvent] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    overflowed: bool = False

    @property
    def fetched(self) -> int:
        """Counts every record returned, normalized or not.

        Returns:
            int: The count.
        """
        return len(self.events) + len(self.rejected)


class PredictHQLimitError(Exception):
    """PredictHQ refused further requests; the run should stop."""


class OutOfCreditsError(PredictHQLimitError):
    """The plan's quota or credits are used up (402 or 403)."""


class RateLimitedError(PredictHQLimitError):
    """PredictHQ answered 429."""


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Requests                         │
#          ╰──────────────────────────────────────────────────────────╯


def client(
    token: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """Builds an authenticated client; close it with `async with`.

    Args:
        token (str): The PredictHQ token.
        transport (httpx.AsyncBaseTransport | None): A transport to use
            instead of the network, e.g. in a test.

    Returns:
        httpx.AsyncClient: The client.
    """
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30.0,
        transport=transport,
    )


def recent_params(
    market: Market, *, updated_since: datetime, radius: str = "10km"
) -> dict[str, Any]:
    """Builds a query for upcoming events revised since a moment.

    Withdrawn and predicted events are asked for too: the API returns only
    active ones by default, and an unseen deletion would leave a cancelled
    event counting as demand. A day of slack keeps in an event running
    tonight in a timezone behind UTC.

    Args:
        market (Market): Where to search.
        updated_since (datetime): Only events revised after this.
        radius (str): How far from the centre, e.g. "10km".

    Returns:
        dict[str, Any]: The query parameters.
    """
    return {
        "within": f"{radius}@{market.latitude},{market.longitude}",
        "updated.gte": updated_since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "active.gte": (datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
        "state": STATES,
        "limit": PAGE_LIMIT,
        "sort": "updated",
    }


def window_params(
    market: Market, start: date, end: date, *, radius: str = "10km"
) -> dict[str, Any]:
    """Builds a query for every event active in a window, with a day of slack.

    Args:
        market (Market): Where to search.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        radius (str): How far from the centre, e.g. "10km".

    Returns:
        dict[str, Any]: The query parameters.
    """
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
    """Fetches every page of a query and normalizes each record.

    Bad records are rejected, not raised. Every event gets the hotel's city,
    so a suburb venue shares a dedupe key with a news article naming the
    city. Each `next` link already carries every query parameter.

    Args:
        http (httpx.AsyncClient): The client.
        params (dict[str, Any]): The query parameters.
        city (str): The hotel's city.
        into (FetchResult | None): A result to add to, so a limit error keeps
            every page fetched before it; None starts a new one.

    Returns:
        FetchResult: The events and rejections.

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
        url, query = body.get("next"), None
    return result


async def get_page(
    http: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Gets one page, once; a failed job records where to resume instead.

    PredictHQ doesn't say which status an exhausted plan returns, so both 402
    and 403 count.

    Args:
        http (httpx.AsyncClient): The client.
        url (str): The page's URL.
        params (dict[str, Any] | None): Query parameters, for the first page.

    Returns:
        dict[str, Any]: The page's JSON.

    Raises:
        OutOfCreditsError: On a 402 or 403.
        RateLimitedError: On a 429.
        httpx.HTTPError: On any other failure.
    """
    response = await http.get(url, params=params)
    if response.status_code == 429:
        raise RateLimitedError(f"HTTP 429: {response.text[:300]}")
    if response.status_code in _OUT_OF_CREDITS:
        raise OutOfCreditsError(f"HTTP {response.status_code}: {response.text[:300]}")
    response.raise_for_status()
    return response.json()


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Records                          │
#          ╰──────────────────────────────────────────────────────────╯


def to_normalized(raw: Mapping[str, Any], *, city: str) -> NormalizedEvent:
    """Turns a PredictHQ record into the shared event shape.

    Args:
        raw (Mapping[str, Any]): The record.
        city (str): The hotel's city.

    Returns:
        NormalizedEvent: The event.

    Raises:
        KeyError: A required field is missing.
        ValueError: A field is malformed.
    """
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


def accommodation(raw: Mapping[str, Any]) -> tuple[float | None, dict[date, float]]:
    """Reads PredictHQ's hotel estimates from a record.

    Only attendance-based impacts are read; a rank-based one is on a
    different scale.

    Args:
        raw (Mapping[str, Any]): The record.

    Returns:
        tuple[float | None, dict[date, float]]: The predicted accommodation
            spend (None if PredictHQ gave none), and the expected guests on
            each night, including nights before and after the event.
    """
    spend = (raw.get("predicted_event_spend_industries") or {}).get("accommodation")
    nights: dict[date, float] = {}
    for pattern in raw.get("impact_patterns") or []:
        if (
            pattern.get("vertical") != "accommodation"
            or pattern.get("impact_type") != "phq_attendance"
        ):
            continue
        for impact in pattern.get("impacts") or []:
            night = date.fromisoformat(impact["date_local"])
            nights[night] = nights.get(night, 0.0) + float(impact["value"])
    return (None if spend is None else float(spend)), nights


def first_seen(raw: Mapping[str, Any]) -> date | None:
    """Reads the UTC date PredictHQ first had the event.

    PredictHQ notes this isn't an announcement date.

    Args:
        raw (Mapping[str, Any]): The record.

    Returns:
        date | None: The date, or None if the record doesn't say.
    """
    value = raw.get("first_seen")
    if not value:
        return None
    return _parse_instant(value).astimezone(UTC).date()


def rejection_reason(exc: Exception) -> str:
    """Describes why a record was rejected.

    Args:
        exc (Exception): What normalizing it raised.

    Returns:
        str: The reason, in words.
    """
    if isinstance(exc, KeyError):
        return f"missing field {exc.args[0]!r}"
    return str(exc)


def _parse_instant(value: str) -> datetime:
    """Reads an ISO timestamp, taking one without a zone as UTC.

    Args:
        value (str): The timestamp.

    Returns:
        datetime: The moment, with a timezone.
    """
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _category(value: str | None) -> EventCategory:
    """Reads a category, defaulting to UNKNOWN.

    Args:
        value (str | None): PredictHQ's category.

    Returns:
        EventCategory: The category.
    """
    try:
        return EventCategory(value)
    except ValueError:
        return EventCategory.UNKNOWN


def _venue(entities: list[Mapping[str, Any]]) -> str | None:
    """Finds the venue's name among a record's entities.

    Args:
        entities (list[Mapping[str, Any]]): The record's entities.

    Returns:
        str | None: The venue's name, or None.
    """
    return next((e.get("name") for e in entities if e.get("type") == "venue"), None)
