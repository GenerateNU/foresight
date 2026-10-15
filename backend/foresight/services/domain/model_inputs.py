"""The signals the pricing model reads, loaded the same way for training and
serving.

Only reads what's already ingested; nothing here fetches from a source. Weather
follows decision 0024:

- A recorded day wins over a forecast for the same day.
- Training uses recorded weather only; a night without it stays empty.
- Serving falls back to the forecast, then to the typical weather for that
  ISO week across every recorded year (week 53 borrows week 52 when no
  recorded year has one), and says which it used.

Events and flights aren't used yet (no history to train on), so both are
passed as empty frames. The feature columns stay fixed (`ml/features.FEATURES`)
so adding them later doesn't change the model's inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from foresight.repository.signals import weather as weather_repo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City

WEATHER_COLUMNS = ["temp_max_c", "precip_mm", "wind_kph"]

# Signals the model has columns for but no data yet.
NO_EVENTS = pd.DataFrame(
    columns=[
        "start_local_date",
        "end_local_date",
        "category",
        "expected_attendance",
        "local_rank",
    ]
)
NO_FLIGHTS = pd.DataFrame(columns=["arrival_date", "flight_count", "avg_fare_eur"])
UNUSED_SIGNALS = {"events": "not used yet", "flights": "not used yet"}


@dataclass(frozen=True, slots=True)
class DailyWeather:
    """One row per day for `build_features`, and where each day's came from."""

    frame: pd.DataFrame  # weather_date + WEATHER_COLUMNS
    sources: dict[date, str]  # "recorded", "forecast", "typical week 43 (4 years)"


async def weather_for(
    session: AsyncSession,
    city: City,
    days: Sequence[date],
    *,
    fallback: bool,
) -> DailyWeather:
    """Weather for each day: recorded, else (with `fallback`) forecast, else
    the typical weather for its ISO week. Days with none are left out of
    `frame` and marked "missing" in `sources`."""
    if not days:
        return DailyWeather(
            pd.DataFrame(columns=["weather_date", *WEATHER_COLUMNS]), {}
        )

    rows = await weather_repo.daily_weather(
        session, city_id=city.id, start=min(days), end=max(days)
    )
    recorded: dict[date, dict] = {}
    forecast: dict[date, dict] = {}
    for row in rows:  # ordered by source, so the first per day is kept
        target = forecast if row["is_forecast"] else recorded
        target.setdefault(row["weather_date"], dict(row))

    picked: dict[date, dict] = {}
    sources: dict[date, str] = {}
    typical_cache: dict[int, dict | None] = {}
    for day in sorted(set(days)):
        if day in recorded:
            picked[day], sources[day] = recorded[day], "recorded"
        elif fallback and day in forecast:
            picked[day], sources[day] = forecast[day], "forecast"
        elif fallback:
            week = day.isocalendar().week
            if week not in typical_cache:
                found = await weather_repo.typical_week(
                    session, city_id=city.id, iso_week=week
                )
                if found is None and week == 53:
                    # Only some years have an ISO week 53; its neighbour is close.
                    found = await weather_repo.typical_week(
                        session, city_id=city.id, iso_week=52
                    )
                typical_cache[week] = dict(found) if found else None
            typical = typical_cache[week]
            if typical is None:
                sources[day] = "missing"
                continue
            picked[day] = typical
            sources[day] = f"typical week {week} ({typical['years']} years)"
        else:
            sources[day] = "missing"

    frame = pd.DataFrame(
        [
            {"weather_date": day, **{c: _float(row[c]) for c in WEATHER_COLUMNS}}
            for day, row in picked.items()
        ],
        columns=["weather_date", *WEATHER_COLUMNS],
    )
    return DailyWeather(frame, sources)


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # avg() returns Decimal
