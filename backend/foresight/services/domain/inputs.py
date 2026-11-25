"""The events the pricing model reads, loaded the same way for training and
serving.

Only reads what's already ingested; nothing here fetches from a source.
Events follow decisions 0041 and 0055: the counted events
(`event.counted_events`, the same rule as the events shown on a night), which
nights an events backfill covered, and when PredictHQ first saw each event. On
a night no backfill covered, the event features stay empty, not zero.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import Source
from foresight.database.models.city import City
from foresight.database.models.hotel import Hotel
from foresight.repository.signals import event as event_repo
from foresight.services.adapters import predicthq
from foresight.services.domain import event as event_service
from foresight.services.ml.features import build_features

EVENT_COLUMNS = [
    "start_local_date",
    "end_local_date",
    "category",
    "expected_attendance",
    "local_rank",
    "latitude",
    "longitude",
]
IMPACT_COLUMNS = ["impact_date", "guests", "first_seen"]
# PredictHQ's accommodation impact reaches a few nights before and after an
# event (up to 3 and 5 in Dublin), so events a week either side still count.
_IMPACT_REACH = timedelta(days=7)

NO_EVENTS = pd.DataFrame(columns=[*EVENT_COLUMNS, "accommodation_spend", "first_seen"])
NO_IMPACTS = pd.DataFrame(columns=IMPACT_COLUMNS)


@dataclass(frozen=True, slots=True)
class CityEvents:
    """Events for `build_features`, the nights an events backfill covered, and
    PredictHQ's expected hotel guests per night from those events."""

    frame: pd.DataFrame  # EVENT_COLUMNS + accommodation_spend + first_seen
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
    seen = {e.id: predicthq.first_seen(payloads.get(e.id, {})) for e in events}
    frame = pd.DataFrame(
        [
            {
                **{c: getattr(event, c) for c in EVENT_COLUMNS},
                "accommodation_spend": estimates[event.id][0],
                "first_seen": seen[event.id],
            }
            for event in events
        ],
        columns=[*EVENT_COLUMNS, "accommodation_spend", "first_seen"],
    )

    # Unknown attendance or rank is None; as floats they become NaN, which
    # `build_features` can sum, rather than a column it can't.
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
            {"impact_date": night, "guests": guests, "first_seen": seen[event_id]}
            for event_id, (_, nights) in estimates.items()
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


@dataclass(frozen=True, slots=True)
class ModelInputs:
    """The model's inputs for some rows, and which nights had event data.

    Attributes:
        x (pd.DataFrame): Every input in FEATURES order, one row per input row.
        events_fetched (set[date]): The nights an events backfill covered.
    """

    x: pd.DataFrame
    events_fetched: set[date]


async def build_inputs(
    session: AsyncSession,
    hotel: Hotel,
    rows: pd.DataFrame,
    *,
    booked_on: pd.Series | date,
) -> ModelInputs:
    """Builds the model's inputs for each row, the same way everywhere.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel, with its city loaded.
        rows (pd.DataFrame): One row per night or booked room, with a
            stay_date column.
        booked_on (pd.Series | date): When each row was booked, aligned with
            `rows`, or one date for every row.

    Returns:
        ModelInputs: The inputs, indexed like `rows`.
    """
    events = await events_for(session, hotel.city, sorted(set(rows["stay_date"])))
    x = build_features(
        rows,
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=booked_on,
    )
    return ModelInputs(x, events.fetched)
