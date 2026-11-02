"""The signals the pricing model reads, loaded the same way for training and
serving.

Only reads what's already ingested; nothing here fetches from a source. Weather
follows decision 0024:

- A recorded day wins over a forecast for the same day.
- Training uses recorded weather only; a night without it stays empty.
- Serving falls back to the forecast, then to the typical weather for that
  ISO week across every recorded year (week 53 borrows week 52 when no
  recorded year has one), and says which it used.

Events follow decision 0040: the counted events (`event.counted_events`, the
same rule as the events shown on a night), and which nights an events
backfill covered. On any other night the event features stay empty, not zero.

Flights aren't used yet (no history to train on), so they're passed as an
empty frame. The feature columns stay fixed (`ml/features.FEATURES`) so
adding them later doesn't change the model's inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd

from foresight.database.enums import Source
from foresight.repository.signals import event as event_repo
from foresight.repository.signals import weather as weather_repo
from foresight.services.adapters import predicthq
from foresight.services.domain import event as event_service

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City
    from foresight.database.models.hotel import Hotel

WEATHER_COLUMNS = ["temp_max_c", "precip_mm", "wind_kph"]

EVENT_COLUMNS = [
    "start_local_date",
    "end_local_date",
    "category",
    "expected_attendance",
    "local_rank",
    "latitude",
    "longitude",
]
IMPACT_COLUMNS = ["impact_date", "guests"]
# PredictHQ's accommodation impact reaches a few nights before and after an
# event (up to 3 and 5 in Dublin), so events a week either side still count.
_IMPACT_REACH = timedelta(days=7)

NO_EVENTS = pd.DataFrame(columns=[*EVENT_COLUMNS, "accommodation_spend"])
NO_IMPACTS = pd.DataFrame(columns=IMPACT_COLUMNS)
# Signals the model has columns for but no data yet.
NO_FLIGHTS = pd.DataFrame(columns=["arrival_date", "flight_count", "avg_fare_eur"])


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


@dataclass(frozen=True, slots=True)
class CityEvents:
    """Events for `build_features`, the nights an events backfill covered, and
    PredictHQ's expected hotel guests per night from those events."""

    frame: pd.DataFrame  # EVENT_COLUMNS + eccommodation_speed
    fetched: set[date]
    impacts: pd.DataFrame  # IMPACT_COLUMNS, one row per event per night


async def events_for(
    session: AsyncSession, city: City, days: Sequence[date]
) -> CityEvents:
    """The counted events on any of `days`, and which of the days an events
    backfill covered. Pass `fetched` to `build_features` as `events_fetched`
    so uncovered nights get empty event features, not zeros."""
    if not days:
        return CityEvents(NO_EVENTS, set(), NO_IMPACTS)
    start, end = min(days), max(days)
    events = await event_service.counted_events(
        session, city.id, start=start - _IMPACT_REACH, end=end + _IMPACT_REACH
    )
    fetched = await event_service.fetched_nights(session, city.id, start=start, end=end)
    payloads = await event_repo.latest_payloads(
        session, [e.id for e in events], source=Source.PREDICTHQ
    )
    estimates = {e.id: predicthq.accommodation(payloads.get(e.id, {})) for e in events}
    frame = pd.DataFrame(
        [
            {
                **{c: getattr(event, c) for c in EVENT_COLUMNS},
                "accommodation_spend": estimates.get(event.id)[0],
            }
            for event in events
        ],
        columns=[*EVENT_COLUMNS, "accommodation_spend"],
    )

    # Unknown attendance or rank is None; as floats they become NaN, which
    # which `build_features` can sum, rather than a column it can't.
    frame = frame.astype(
        {
            "expected_attendance": float,
            "local_rank": float,
            "accommodation_spend": float,
            "latitude": float,
            "longitude": float,
        }
    )
    impacts = pd.DataFrame(
        [
            {"impact_date": night, "guests": guests}
            for _, nights in estimates.values()
            for night, guests in nights.items()
        ],
        columns=IMPACT_COLUMNS,
    )
    return CityEvents(frame, fetched, impacts)


def hotel_location(hotel: Hotel) -> tuple[float, float] | None:
    """The hotel's (latitude, longitude), or None if either is missing."""
    if hotel.latitude is None or hotel.longitude is None:
        return None
    return hotel.latitude, hotel.longitude


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # avg() returns Decimal
