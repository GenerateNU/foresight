from __future__ import annotations

from datetime import date

import pandas as pd

from foresight.ingest.flights import daily_arrivals

DUBLIN = "Europe/Dublin"


def _df(*timestamps: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"arrival_time": pd.to_datetime(list(timestamps), utc=True).tz_convert(DUBLIN)}
    )


def test_counts_flights_per_local_day() -> None:
    rows = daily_arrivals(
        _df("2026-06-01T08:00Z", "2026-06-01T19:00Z", "2026-06-02T08:00Z"),
        airport="DUB",
        source="aerodatabox",
    )
    assert [(r["arrival_date"], r["flight_count"]) for r in rows] == [
        (date(2026, 6, 1), 2),
        (date(2026, 6, 2), 1),
    ]


def test_late_utc_arrival_counts_on_the_local_day() -> None:
    # 23:30Z on 1 June is 00:30 on 2 June in Dublin summer time.
    rows = daily_arrivals(_df("2026-06-01T23:30Z"), airport="DUB", source="opensky")
    assert rows[0]["arrival_date"] == date(2026, 6, 2)


def test_row_matches_the_table_columns() -> None:
    (row,) = daily_arrivals(_df("2026-06-01T08:00Z"), airport="DUB", source="opensky")
    assert row == {
        "airport": "DUB",
        "arrival_date": date(2026, 6, 1),
        "flight_count": 1,
        "avg_fare_eur": None,
        "source": "opensky",
    }


def test_no_flights_is_no_rows() -> None:
    assert daily_arrivals(pd.DataFrame(), airport="DUB", source="opensky") == []
