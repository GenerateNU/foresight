import pandas as pd

from foresight.database.enums import EventCategory

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
    "temp_max_c",
    "precip_mm",
    "wind_kph",
    "flight_count",
    "avg_fare_eur",
]

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
    weather: pd.DataFrame,
    flights: pd.DataFrame,
) -> pd.DataFrame:
    """Builds the model's input columns, one row per room type per night.

    Used for training (past nights) and serving (the night being priced), so
    both see identical features. Missing weather or flight data stays empty;
    the model learns a separate effect for unknown values.

    Args:
        nights (pd.DataFrame): One row per room type per night, with columns
            stay_date and room_type.
        events (pd.DataFrame): Active events in the hotel's city, with columns
            start_local_date, end_local_date, category, expected_attendance,
            and local_rank.
        weather (pd.DataFrame): At most one row per day, with columns
            weather_date, temp_max_c, precip_mm, and wind_kph.
        flights (pd.DataFrame): At most one row per day for the hotel's
            airport, with columns arrival_date, flight_count, and avg_fare_eur.

    Returns:
        pd.DataFrame: The FEATURES columns, in order, indexed like nights.

    Raises:
        ValueError: If weather or flights has more than one row for a day.
    """
    stay_date = pd.to_datetime(nights["stay_date"])
    dates = pd.DatetimeIndex(stay_date.unique())

    daily = (
        _event_features(events, dates)
        .join(_daily(weather, "weather_date", ["temp_max_c", "precip_mm", "wind_kph"]))
        .join(_daily(flights, "arrival_date", ["flight_count", "avg_fare_eur"]))
    )

    features = daily.reindex(stay_date).set_index(nights.index)
    features["room_type"] = nights["room_type"].astype("category")
    features["day_of_week"] = stay_date.dt.dayofweek.to_numpy()
    features["month"] = stay_date.dt.month.to_numpy()
    return features.reindex(columns=FEATURES)


def _event_features(events: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
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
    by_date = expanded.groupby("date")

    for column, category in [
        ("is_public_holiday", EventCategory.PUBLIC_HOLIDAYS.value),
        ("is_school_holiday", EventCategory.SCHOOL_HOLIDAYS.value),
    ]:
        flagged = by_date["category"].agg(lambda c, cat=category: int((c == cat).any()))
        result.loc[flagged.index, column] = flagged

    attended = expanded.loc[expanded["category"].isin(ATTENDED_CATEGORIES)]
    if not attended.empty:
        totals = attended.groupby("date").agg(
            event_count=("category", "size"),
            event_attendance=("expected_attendance", "sum"),
            event_rank_max=("local_rank", "max"),
        )
        totals = totals.fillna(0)
        result.loc[totals.index, totals.columns] = totals
    return result


def _daily(df: pd.DataFrame, date_column: str, columns: list[str]) -> pd.DataFrame:
    """Indexes one-row-per-day data by date.

    Args:
        df (pd.DataFrame): The daily data.
        date_column (str): Which column holds the date.
        columns (list[str]): Which columns to keep.

    Returns:
        pd.DataFrame: The columns, indexed by date.

    Raises:
        ValueError: If any date appears more than once.
    """
    daily = (
        df.assign(**{date_column: pd.to_datetime(df[date_column])})
        .set_index(date_column)
        .reindex(columns=columns)
    )
    if daily.index.has_duplicates:
        raise ValueError(f"expected at most one row per {date_column}")
    return daily.astype(float)
