"""OpenSky adapter: arrivals per airport per day, from ADS-B tracking.

Historical only: OpenSky has flights up to yesterday (UTC). A request may span
at most 2 UTC days and costs credits from a daily allowance, so a long range is
fetched in 2-day chunks and stops cleanly when the allowance runs out. No DB
writes.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ARRIVAL_URL = "https://opensky-network.org/api/flights/arrival"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
SOURCE = "opensky"
CHUNK_DAYS = 2


class CreditsExhaustedError(Exception):
    """OpenSky's daily credit allowance is used up; `retry_after` is in seconds."""

    def __init__(self, retry_after: str | None) -> None:
        super().__init__(f"OpenSky credit limit reached, retry in {retry_after}s")
        self.retry_after = retry_after


class OpenSkyClient:
    """Authenticated OpenSky access; refreshes its token when it expires."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.AsyncClient(timeout=60.0, transport=transport)
        self._token: str | None = None

    async def __aenter__(self) -> OpenSkyClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    async def daily_arrivals(
        self, start: date, end: date, *, airport_icao: str, timezone: str
    ) -> AsyncIterator[tuple[date, int]]:
        """(local day, arrival count) for each day from `start` to `end`.

        `end` is clamped to yesterday (UTC). Yields per chunk, oldest first,
        so a caller can save as it goes; days with no flights yield 0.

        Raises:
            CreditsExhaustedError: When the daily allowance runs out; every
                day yielded before it is complete.
        """
        zone = ZoneInfo(timezone)
        end = min(end, datetime.now(UTC).date() - timedelta(days=1))
        first = start
        while first <= end:
            last = min(first + timedelta(days=CHUNK_DAYS - 1), end)
            counts: Counter[date] = Counter()
            for flight in await self._arrivals(first, last, airport_icao):
                landed = datetime.fromtimestamp(flight["lastSeen"], UTC)
                counts[landed.astimezone(zone).date()] += 1
            day = first
            while day <= last:
                yield day, counts[day]
                day += timedelta(days=1)
            first = last + timedelta(days=1)

    async def _arrivals(self, first: date, last: date, airport_icao: str) -> list:
        # Midnight UTC to the last second of `last`: never more than 2 UTC days.
        begin = datetime.combine(first, time.min, UTC)
        until = datetime.combine(last + timedelta(days=1), time.min, UTC)
        params = {
            "airport": airport_icao,
            "begin": int(begin.timestamp()),
            "end": int(until.timestamp()) - 1,
        }
        for _ in range(2):
            response = await self._http.get(
                ARRIVAL_URL,
                params=params,
                headers={"Authorization": f"Bearer {await self._access_token()}"},
            )
            if response.status_code != 401:
                break
            self._token = None  # expired: fetch a new one and retry once
        if response.status_code == 429:
            raise CreditsExhaustedError(
                response.headers.get("X-Rate-Limit-Retry-After-Seconds")
            )
        if response.status_code == 404:  # no flights in this chunk
            return []
        response.raise_for_status()
        return response.json()

    async def _access_token(self) -> str:
        if self._token is None:
            response = await self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            response.raise_for_status()
            self._token = response.json()["access_token"]
        return self._token
