"""Open-Meteo adapter against a mocked API: row mapping, chunking, clamping."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from foresight.services.adapters import open_meteo
from foresight.services.adapters.open_meteo import chunks, condition, rows

TODAY = date(2026, 6, 10)


def _body(days: list[str], **columns: list[Any]) -> dict[str, Any]:
    n = len(days)
    defaults = {
        "temperature_2m_max": [18.4] * n,
        "temperature_2m_min": [9.1] * n,
        "precipitation_sum": [0.0] * n,
        "wind_speed_10m_max": [14.0] * n,
        "weather_code": [3] * n,
    }
    return {"daily": {"time": days, **(defaults | columns)}}


async def _no_sleep(_seconds: float) -> None:
    return None


def test_row_matches_the_table_columns() -> None:
    (row,) = rows(_body(["2026-06-01"]), "Dublin", is_forecast=True)
    assert row == {
        "city": "Dublin",
        "weather_date": date(2026, 6, 1),
        "temp_max_c": 18.4,
        "temp_min_c": 9.1,
        "precip_mm": 0.0,
        "wind_kph": 14.0,
        "condition": "cloudy",
        "is_forecast": True,
        "source": "open-meteo",
    }


def test_the_local_date_is_kept_as_given() -> None:
    # With `timezone` set, Open-Meteo's `time` is already the local calendar
    # day, which is what weather_date has to join to stay_date on.
    days = ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert [r["weather_date"] for r in rows(_body(days), "D", is_forecast=False)] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 6, 3),
    ]


def test_missing_measures_become_null() -> None:
    nulls = dict.fromkeys(
        (
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "wind_speed_10m_max",
            "weather_code",
        ),
        [None],
    )
    (row,) = rows(_body(["2026-06-01"], **nulls), "Dublin", is_forecast=False)
    assert row["temp_max_c"] is None
    assert row["condition"] is None


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (0, "clear"),
        (2, "partly cloudy"),
        (3, "cloudy"),
        (45, "fog"),
        (48, "fog"),
        (57, "drizzle"),
        (67, "rain"),
        (77, "snow"),
        (82, "rain showers"),
        (86, "snow showers"),
        (95, "thunderstorm"),
    ],
)
def test_wmo_code_becomes_a_condition(code: int, label: str) -> None:
    assert condition(code) == label


def test_long_ranges_are_split_a_year_at_a_time() -> None:
    assert list(chunks(date(2024, 1, 1), date(2025, 6, 30))) == [
        (date(2024, 1, 1), date(2024, 12, 30)),
        (date(2024, 12, 31), date(2025, 6, 30)),
    ]


def test_a_short_range_is_one_request() -> None:
    assert list(chunks(date(2025, 6, 1), date(2025, 6, 1))) == [
        (date(2025, 6, 1), date(2025, 6, 1))
    ]


async def test_actuals_are_never_asked_past_today() -> None:
    asked: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        asked.append((params["start_date"], params["end_date"]))
        return httpx.Response(200, json=_body([params["start_date"]]))

    async with open_meteo.client(transport=httpx.MockTransport(handler)) as http:
        await open_meteo.fetch_actuals(
            http,
            city="Dublin",
            latitude=53.3,
            longitude=-6.2,
            start=date(2026, 6, 1),
            end=date(2026, 7, 31),
            today=TODAY,
            sleep=_no_sleep,
        )
    assert asked == [("2026-06-01", "2026-06-10")]


async def test_forecast_asks_for_the_daily_measures_in_local_time() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_body(["2026-06-11"]))

    async with open_meteo.client(transport=httpx.MockTransport(handler)) as http:
        (row,) = await open_meteo.fetch_forecast(
            http, city="Dublin", latitude=53.3, longitude=-6.2, sleep=_no_sleep
        )
    params = seen[0].url.params
    assert seen[0].url.host == "api.open-meteo.com"
    assert params["timezone"] == "auto"
    assert params["forecast_days"] == "16"
    assert row["is_forecast"] is True


async def test_a_bad_request_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": True, "reason": "bad"})

    async with open_meteo.client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await open_meteo.fetch_forecast(
                http, city="D", latitude=0, longitude=0, sleep=_no_sleep
            )
