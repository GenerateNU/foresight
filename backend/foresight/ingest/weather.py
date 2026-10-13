from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE = "open-meteo"
# A year per archive request keeps each call small; a failure only redoes that year.
CHUNK_DAYS = 365

# Order matters: the response exposes variables by index, not by name.
_DAILY = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "weather_code",
)


_client: openmeteo_requests.Client | None = None


def _get_client() -> openmeteo_requests.Client:
    """The shared Open-Meteo client, created on first use.

    Creating it opens a requests-cache file, so importing this module must not.
    """
    global _client
    if _client is None:
        session = retry(
            requests_cache.CachedSession(".cache", expire_after=3600),
            retries=5,
            backoff_factor=0.2,
        )
        _client = openmeteo_requests.Client(session=session)  # type: ignore[arg-type]
    return _client


def _condition(code: float | None) -> str | None:
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


def _number(value: Any) -> float | None:
    """Open-Meteo pads missing days with NaN, which Postgres cannot store."""
    return None if pd.isna(value) else float(value)


def _rows(response: Any, city: str, *, is_forecast: bool) -> list[dict[str, Any]]:
    daily = response.Daily()
    columns = [daily.Variables(i).ValuesAsNumpy() for i in range(len(_DAILY))]
    # Time() is the UTC instant of local midnight, so east of Greenwich it
    # falls on the previous calendar day; the offset recovers the local day.
    offset = response.UtcOffsetSeconds()
    dates = pd.date_range(
        start=pd.to_datetime(daily.Time() + offset, unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd() + offset, unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left",
    ).date

    temp_max, temp_min, precip, wind, code = columns
    return [
        {
            "city": city,
            "weather_date": day,
            "temp_max_c": _number(temp_max[i]),
            "temp_min_c": _number(temp_min[i]),
            "precip_mm": _number(precip[i]),
            "wind_kph": _number(wind[i]),
            "condition": _condition(_number(code[i])),
            "is_forecast": is_forecast,
            "source": SOURCE,
        }
        for i, day in enumerate(dates)
    ]


def fetch_forecast(
    city: str,
    latitude: float,
    longitude: float,
    timezone: str,
    *,
    days: int = 16,
) -> list[dict[str, Any]]:
    """The next `days` of forecast for one city, as `weather` rows."""
    response = _get_client().weather_api(
        FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": list(_DAILY),
            "timezone": timezone,
            "forecast_days": days,
        },
    )[0]
    return _rows(response, city, is_forecast=True)


def fetch_actuals(
    city: str,
    latitude: float,
    longitude: float,
    timezone: str,
    *,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Recorded weather for `start`..`end` inclusive, as `weather` rows.

    The archive covers 1940-01-01 up to today and rejects anything beyond it
    outright, so a caller backfilling a date range has to clamp `end` to
    today rather than relying on empty rows coming back.
    """
    rows: list[dict[str, Any]] = []
    for chunk_start, chunk_end in chunks(start, end):
        response = _get_client().weather_api(
            ARCHIVE_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": list(_DAILY),
                "timezone": timezone,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
            },
        )[0]
        rows += _rows(response, city, is_forecast=False)
    return rows


def chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Split `start`..`end` into back-to-back spans of at most CHUNK_DAYS days."""
    while start <= end:
        chunk_end = min(start + timedelta(days=CHUNK_DAYS - 1), end)
        yield start, chunk_end
        start = chunk_end + timedelta(days=1)
