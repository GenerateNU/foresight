from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


def daily_arrivals(
    df: pd.DataFrame, *, airport: str, source: str
) -> list[dict[str, Any]]:
    """One row per arrival date, as `flight_arrivals` rows.

    `arrival_time` is already local to the airport, so its date is the day the
    hotel sees those arrivals. No source carries fares, so avg_fare_eur is null.
    """
    if df.empty:
        return []

    counts = df["arrival_time"].dt.date.value_counts().sort_index()
    return [
        {
            "airport": airport,
            "arrival_date": day,
            "flight_count": int(n),
            "avg_fare_eur": None,
            "source": source,
        }
        for day, n in counts.items()
    ]
