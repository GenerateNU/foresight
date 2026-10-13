from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from foresight.ingest.weather import _rows

_DAY = 86400
# temperature_2m_max, temperature_2m_min, precipitation_sum, wind_speed_10m_max,
# weather_code -- the order `_DAILY` requests them in.
_ONE_DAY = ([18.4], [9.1], [0.0], [14.0], [3.0])


def _response(
    columns: tuple[list[float], ...],
    *,
    offset_hours: int = 1,
    first_day: str = "2026-06-01",
) -> SimpleNamespace:
    # Open-Meteo reports local midnight as a UTC instant, so the fixture has to
    # subtract the offset the same way the real response does.
    start = int(pd.Timestamp(first_day, tz="UTC").timestamp()) - offset_hours * 3600
    days = len(columns[0])
    daily = SimpleNamespace(
        Time=lambda: start,
        TimeEnd=lambda: start + days * _DAY,
        Interval=lambda: _DAY,
        Variables=lambda i: SimpleNamespace(
            ValuesAsNumpy=lambda: np.array(columns[i], dtype=float)
        ),
    )
    return SimpleNamespace(
        Daily=lambda: daily, UtcOffsetSeconds=lambda: offset_hours * 3600
    )


@pytest.mark.parametrize("offset_hours", [-11, -5, 0, 1, 13])
def test_local_calendar_day_survives_the_utc_offset(offset_hours: int) -> None:
    # The day the hotel sees, not the UTC instant it started: weather_date
    # joins to stay_date, so a one-day shift mis-attributes every night.
    rows = _rows(
        _response(_ONE_DAY, offset_hours=offset_hours), "Dublin", is_forecast=False
    )
    assert [r["weather_date"] for r in rows] == [date(2026, 6, 1)]


def test_a_range_comes_back_one_row_per_day() -> None:
    three_days = (
        [18.4, 19.0, 17.2],
        [9.1, 10.0, 8.8],
        [0.0, 1.2, 4.0],
        [14.0, 12.0, 20.0],
        [3.0, 61.0, 95.0],
    )
    rows = _rows(_response(three_days), "Dublin", is_forecast=False)
    assert [r["weather_date"] for r in rows] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 6, 3),
    ]
    assert [r["condition"] for r in rows] == ["cloudy", "rain", "thunderstorm"]


@pytest.mark.parametrize(
    ("code", "condition"),
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
def test_wmo_code_becomes_a_condition(code: int, condition: str) -> None:
    columns = (*_ONE_DAY[:4], [float(code)])
    (row,) = _rows(_response(columns), "Dublin", is_forecast=True)
    assert row["condition"] == condition


def test_missing_measures_become_null() -> None:
    # Open-Meteo pads days it has no data for with NaN, which Postgres rejects.
    nans = tuple([float("nan")] for _ in range(5))
    (row,) = _rows(_response(nans), "Dublin", is_forecast=True)
    assert row["temp_max_c"] is None
    assert row["temp_min_c"] is None
    assert row["precip_mm"] is None
    assert row["wind_kph"] is None
    assert row["condition"] is None


def test_row_matches_the_table_columns() -> None:
    (row,) = _rows(_response(_ONE_DAY), "Dublin", is_forecast=True)
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
