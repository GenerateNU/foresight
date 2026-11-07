from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from foresight.database.enums import EventCategory

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import date

# Events whose predicted accommodation spend reaches this are "big" (decision
# 0041). A starting point from 14 Dublin nights; the backtest may change it.
BIG_EVENT_SPEND = 100_000
_EARTH_RADIUS_KM = 6371.0

# Model input columns, in order. Training and serving both use this list.
FEATURES = [
    "room_type",
    "day_of_week",
    "month",
    "is_public_holiday",
    "is_school_holiday",
    "event_count",
    "event_attendance",
    "event_rank_max",
    "event_accommodation_impact",
    "big_event_count",
    "nearest_big_event_km",
]

# FEATURES by kind, for choosing which inputs a backtest trains on. Every
# input is in exactly one group. The holiday flags sit with events: they come
# from the same PredictHQ data, and are unknown on the same nights. Weather
# stays out of the model (decision 0055).
INPUT_GROUPS = {
    "calendar": ["room_type", "day_of_week", "month"],
    "events": [
        "is_public_holiday",
        "is_school_holiday",
        "event_count",
        "event_attendance",
        "event_rank_max",
        "event_accommodation_impact",
        "big_event_count",
        "nearest_big_event_km",
    ],
}

# Events that bring people to the city. Holidays become their own flags, and
# categories like disasters or airport delays aren't counted as demand.
ATTENDED_CATEGORIES = [
    EventCategory.ACADEMIC.value,
    EventCategory.COMMUNITY.value,
    EventCategory.CONCERTS.value,
    EventCategory.CONFERENCES.value,
    EventCategory.EXPOS.value,
    EventCategory.FESTIVALS.value,
    EventCategory.PERFORMING_ARTS.value,
    EventCategory.SPORTS.value,
]


def build_features(
    nights: pd.DataFrame,
    events: pd.DataFrame,
    *,
    events_fetched: Collection[date] | None = None,
    events_impacts: pd.DataFrame | None = None,
    hotel_location: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Builds the model's input columns, one row per room type per night.

    Used for training (past nights) and serving (the night being priced), so
    both see identical features. The event columns stay empty on nights no
    events backfill covered; the model learns a separate effect for unknown
    values.

    An event counts on a night only if PredictHQ first saw it before that
    night (decision 0055), so training never learns from an event the market
    couldn't have known about. Rows without `first_seen` always count.

    Args:
        nights (pd.DataFrame): One row per room type per night, with columns
            stay_date and room_type.
        events (pd.DataFrame): Active events in the hotel's city, with columns
            start_local_date, end_local_date, category, expected_attendance,
            local_rank, and optionally first_seen.
        events_fetched (Collection[date] | None): Nights an events backfill
            covered. On any other night the event columns stay empty: no
            events there means unknown, not quiet (decision 0041). None
            treats every night as covered.
        events_impacts (pd.DataFrame | None): Predicted accommodation impacts
            for each event, with columns impact_date, guests, and optionally
            first_seen. None means no impact data available.
        hotel_location (tuple[float, float] | None): The hotel's latitude and
            longitude, for the distance to the nearest big event. None leaves
            that distance empty.

    Returns:
        pd.DataFrame: The FEATURES columns, in order, indexed like nights.
    """
    stay_date = pd.to_datetime(nights["stay_date"])
    dates = pd.DatetimeIndex(stay_date.unique())

    daily = _event_features(events, dates, hotel_location).join(
        _impact(events_impacts, dates)
    )
    if events_fetched is not None:
        known = dates.isin(pd.to_datetime(list(events_fetched)))
        daily = daily.where(pd.Series(known, index=dates), axis=0)

    features = daily.reindex(stay_date).set_index(nights.index)
    features["room_type"] = nights["room_type"].astype("category")
    features["day_of_week"] = stay_date.dt.dayofweek.to_numpy()
    features["month"] = stay_date.dt.month.to_numpy()
    return features.reindex(columns=FEATURES)


def _event_features(
    events: pd.DataFrame,
    dates: pd.DatetimeIndex,
    hotel_location: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Summarizes the events happening on each date.

    A multi-day event counts on every night from its start to its end date.

    Args:
        events (pd.DataFrame): See build_features.
        dates (pd.DatetimeIndex): The nights to summarize.

    Returns:
        pd.DataFrame: Holiday flags and event totals, indexed by date.
    """
    result = pd.DataFrame(
        {
            "is_public_holiday": 0,
            "is_school_holiday": 0,
            "event_count": 0,
            "event_attendance": 0.0,
            "event_rank_max": 0.0,
            "big_event_count": 0,
            "nearest_big_event_km": float("nan"),
        },
        index=dates,
    )
    if events.empty:
        return result

    # str() turns EventCategory members into their values, e.g. "concerts".
    expanded = events.assign(
        category=events["category"].astype(str),
        date=[
            pd.date_range(start, end)
            for start, end in zip(
                events["start_local_date"], events["end_local_date"], strict=True
            )
        ],
    ).explode("date")
    expanded = expanded.loc[expanded["date"].isin(dates.to_list())]
    expanded = expanded.loc[_known_before(expanded, expanded["date"])]
    by_date = expanded.groupby("date")

    for column, category in [
        ("is_public_holiday", EventCategory.PUBLIC_HOLIDAYS.value),
        ("is_school_holiday", EventCategory.SCHOOL_HOLIDAYS.value),
    ]:
        flagged = by_date["category"].agg(lambda c, cat=category: int((c == cat).any()))
        result.loc[flagged.index, column] = flagged

    attended = expanded.loc[expanded["category"].isin(ATTENDED_CATEGORIES)]
    if not attended.empty:
        big = attended["accommodation_spend"] >= BIG_EVENT_SPEND
        attended = attended.assign(
            big_event_km=_km_from(
                hotel_location, attended["latitude"], attended["longitude"]
            ).where(big)
        )
        totals = attended.groupby("date").agg(
            event_count=("category", "size"),
            event_attendance=("expected_attendance", "sum"),
            event_rank_max=("local_rank", "max"),
            big_event_count=(
                "accommodation_spend",
                lambda x: int((x >= BIG_EVENT_SPEND).sum()),
            ),
            nearest_big_event_km=("big_event_km", "min"),
        )
        # The distance stays empty without a big event: 0 km would mean next door.
        totals = totals.fillna(
            {c: 0 for c in totals.columns if c != "nearest_big_event_km"}
        )
        result.loc[totals.index, totals.columns] = totals
    return result


def _km_from(
    location: tuple[float, float] | None, latitude: pd.Series, longitude: pd.Series
) -> pd.Series:
    """Great-circle distance in km from `location` to each point (haversine).

    Empty everywhere when `location` is None, e.g. a hotel without coordinates.
    """
    if location is None:
        return pd.Series(float("nan"), index=latitude.index)
    lat1, lon1 = np.radians(location[0]), np.radians(location[1])
    lat2, lon2 = np.radians(latitude), np.radians(longitude)
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _impact(impacts: pd.DataFrame | None, dates: pd.DatetimeIndex) -> pd.Series:
    """PredictHQ's expected hotel guests from events, summed per night."""
    if impacts is None or impacts.empty:
        return pd.Series(0.0, index=dates, name="event_accommodation_impact")
    night = pd.to_datetime(impacts["impact_date"])
    impacts = impacts.loc[_known_before(impacts, night)]
    per_night = impacts.groupby(night[impacts.index])["guests"].sum()
    return per_night.reindex(dates, fill_value=0.0).rename("event_accommodation_impact")


def _known_before(rows: pd.DataFrame, night: pd.Series) -> pd.Series:
    """True where PredictHQ first saw the row's event before `night`, or where
    there's no `first_seen` to judge by (decision 0055)."""
    if "first_seen" not in rows.columns:
        return pd.Series(True, index=rows.index)
    first_seen = pd.to_datetime(rows["first_seen"])
    return first_seen.isna() | (first_seen < pd.to_datetime(night))
