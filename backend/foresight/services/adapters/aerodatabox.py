"""AeroDataBox adapter (via RapidAPI): scheduled arrivals per airport per day.

Each day costs about 4 API units; the free plan has 400 a month. No DB writes.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    type Sleep = Callable[[float], Awaitable[None]]

HOST = "aerodatabox.p.rapidapi.com"
SOURCE = "aerodatabox"
# RapidAPI's basic plan allows about one request a second.
PACE_SECONDS = 1.1

_PARAMS = {
    "direction": "Arrival",
    "withCancelled": "false",
    "withCodeshared": "false",
    "withCargo": "false",
    "withPrivate": "false",
    "withLocation": "false",
}


class RateLimitedError(Exception):
    """AeroDataBox answered 429: the monthly quota, or requests too fast."""


def client(
    api_key: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """An authenticated client; close it with `async with`."""
    return httpx.AsyncClient(
        base_url=f"https://{HOST}",
        headers={"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": HOST},
        timeout=30.0,
        transport=transport,
    )


async def count_arrivals(
    http: httpx.AsyncClient,
    day: date,
    *,
    airport_iata: str,
    sleep: Sleep = asyncio.sleep,
) -> int:
    """Flights scheduled to arrive at `airport_iata` on `day` (airport local time).

    The API allows at most 12 hours per request, so a day is two requests.
    Delayed flights scheduled for the day before are skipped, and a flight
    returned by both windows counts once.

    Raises:
        RateLimitedError: If AeroDataBox answers 429.
        httpx.HTTPStatusError: If a request fails otherwise.
    """
    seen: set[tuple[Any, ...]] = set()
    midnight = datetime.combine(day, time.min)
    for window_start in (midnight, midnight + timedelta(hours=12)):
        window_end = window_start + timedelta(hours=11, minutes=59)
        await sleep(PACE_SECONDS)
        response = await _get(
            http,
            f"/flights/airports/iata/{airport_iata}"
            f"/{window_start:%Y-%m-%dT%H:%M}/{window_end:%Y-%m-%dT%H:%M}",
        )
        if response.status_code == 204:  # no flights in this window
            continue
        for item in response.json().get("arrivals", []):
            move = item.get("movement") or {}
            scheduled = move.get("scheduledTime") or {}
            if not scheduled.get("local", "").startswith(day.isoformat()):
                continue
            origin = (move.get("airport") or {}).get("iata")
            seen.add((item.get("number"), scheduled.get("utc"), origin))
    return len(seen)


async def _get(http: httpx.AsyncClient, path: str) -> httpx.Response:
    response = await http.get(path, params=_PARAMS)
    if response.status_code == 429:
        raise RateLimitedError(response.text[:300])
    response.raise_for_status()
    return response
