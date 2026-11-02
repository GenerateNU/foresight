"""Simple forecasting rules the pricing model has to beat.

Each one predicts a rate per room type per night from past nights alone, with
no training. The backtest scores them next to the model; if the model can't
beat them, its features aren't adding value.

Both take `history` and `targets` with columns stay_date, room_type and rate
(targets need no rate), and return one prediction per target row, indexed like
`targets`. A night with no history to draw on gets NaN.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# 52 weeks: the same weekday a year earlier.
LAST_YEAR = timedelta(days=364)


def same_weekday_last_year(history: pd.DataFrame, targets: pd.DataFrame) -> pd.Series:
    """The room type's rate on the same weekday 52 weeks before each night."""
    rates = history.set_index(["room_type", "stay_date"])["rate"]
    keys = pd.MultiIndex.from_arrays(
        [targets["room_type"], targets["stay_date"] - LAST_YEAR]
    )
    return pd.Series(rates.reindex(keys).to_numpy(), index=targets.index, dtype=float)


def recent_weekday_mean(
    history: pd.DataFrame, targets: pd.DataFrame, cutoff: date, *, weeks: int = 4
) -> pd.Series:
    """The room type's mean rate on that weekday over the `weeks` up to `cutoff`.

    Anchored at the cutoff, not each night, so it uses only what was known on
    the day the forecast was made, just like the model.
    """
    start = cutoff - timedelta(weeks=weeks)
    recent = history.loc[
        (history["stay_date"] > start) & (history["stay_date"] <= cutoff)
    ]
    by = [recent["room_type"], _weekday(recent["stay_date"])]
    means = recent.groupby(by)["rate"].mean()
    keys = pd.MultiIndex.from_arrays(
        [targets["room_type"], _weekday(targets["stay_date"])]
    )
    return pd.Series(means.reindex(keys).to_numpy(), index=targets.index, dtype=float)


def _weekday(stay_date: pd.Series) -> pd.Series:
    return pd.to_datetime(stay_date).dt.dayofweek.rename("weekday")
