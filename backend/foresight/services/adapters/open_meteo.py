"""Open-Meteo adapter: daily forecasts and recorded weather as `weather` rows.

Uses the plain JSON API. With `timezone` set, Open-Meteo returns each day as
the local calendar date, so `weather_date` joins to a hotel's stay_date as-is.
No DB writes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE = "open-meteo"
# The forecast reaches 16 days; further-out nights have no forecast row.
FORECAST_DAYS = 16
# A year per archive request keeps each call small; a failure only redoes that year.
CHUNK_DAYS = 365

_DAILY = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "weather_code",
)


def client(*, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """A client for either Open-Meteo endpoint; close it with `async with`."""
    return httpx.AsyncClient(timeout=60.0, transport=transport)


async def fetch_forecast(
    http: httpx.AsyncClient,
    *,
    latitude: float,
    longitude: float,
    timezone: str = "auto",
    days: int = FORECAST_DAYS,
) -> list[dict[str, Any]]:
    """The next `days` of forecast at a point, as `weather` rows."""
    body = await _get(
        http,
        FORECAST_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join(_DAILY),
            "timezone": timezone,
            "forecast_days": days,
        },
    )
    return rows(body, is_forecast=True)


async def fetch_actuals(
    http: httpx.AsyncClient,
    *,
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    timezone: str = "auto",
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Recorded weather for `start`..`end` inclusive, as `weather` rows.

    The archive rejects any date after today outright rather than returning
    empty days, so `end` is clamped to today here.
    """
    end = min(end, today or date.today())
    out: list[dict[str, Any]] = []
    for chunk_start, chunk_end in chunks(start, end):
        body = await _get(
            http,
            ARCHIVE_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(_DAILY),
                "timezone": timezone,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
            },
        )
        out += rows(body, is_forecast=False)
    return out


def rows(body: dict[str, Any], *, is_forecast: bool) -> list[dict[str, Any]]:
    """An Open-Meteo `daily` block as `weather` rows, without `city_id`.

    Missing values are null.
    """
    daily = body["daily"]
    temp_max, temp_min, precip, wind, code = (daily[name] for name in _DAILY)
    return [
        {
            "weather_date": date.fromisoformat(day),
            "temp_max_c": temp_max[i],
            "temp_min_c": temp_min[i],
            "precip_mm": precip[i],
            "wind_kph": wind[i],
            "condition": condition(code[i]),
            "is_forecast": is_forecast,
            "source": SOURCE,
        }
        for i, day in enumerate(daily["time"])
    ]


def condition(code: float | None) -> str | None:
    """A WMO 4677 code as the short label `condition` carries."""
    if code is None:
        return None
    code = int(code)
    if code == 0:
        return "clear"
    if code <= 2:
        return "partly cloudy"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code <= 57:
        return "drizzle"
    if code <= 67:
        return "rain"
    if code <= 77:
        return "snow"
    if code <= 82:
        return "rain showers"
    if code <= 86:
        return "snow showers"
    return "thunderstorm"


def chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Split `start`..`end` into back-to-back spans of at most CHUNK_DAYS days."""
    while start <= end:
        chunk_end = min(start + timedelta(days=CHUNK_DAYS - 1), end)
        yield start, chunk_end
        start = chunk_end + timedelta(days=1)


async def _get(
    http: httpx.AsyncClient, url: str, params: dict[str, Any]
) -> dict[str, Any]:
    response = await http.get(url, params=params)
    response.raise_for_status()
    return response.json()
