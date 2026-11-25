from datetime import date, timedelta

import pandas as pd

LAST_YEAR = timedelta(days=364)


def same_weekday_last_year(history: pd.DataFrame, targets: pd.DataFrame) -> pd.Series:
    """Predicts each night's rate as the same weekday's 52 weeks earlier.

    A rule the model has to beat, with no training.

    Args:
        history (pd.DataFrame): Past nights, with stay_date and rate.
        targets (pd.DataFrame): The nights to predict, with stay_date.

    Returns:
        pd.Series: One prediction per target, indexed like `targets`; NaN
            where there's no history.
    """
    rates = history.set_index("stay_date")["rate"]
    keys = targets["stay_date"] - LAST_YEAR
    return pd.Series(rates.reindex(keys).to_numpy(), index=targets.index, dtype=float)


def recent_weekday_mean(
    history: pd.DataFrame, targets: pd.DataFrame, cutoff: date, *, weeks: int = 4
) -> pd.Series:
    """Predicts each night's rate as its weekday's mean over recent weeks.

    A rule the model has to beat, with no training. Anchored at the cutoff,
    not each night, so it uses only what was known that day, like the model.

    Args:
        history (pd.DataFrame): Past nights, with stay_date and rate.
        targets (pd.DataFrame): The nights to predict, with stay_date.
        cutoff (date): The last night known.
        weeks (int): How many weeks before the cutoff to average.

    Returns:
        pd.Series: One prediction per target, indexed like `targets`; NaN
            where there's no history.
    """
    start = cutoff - timedelta(weeks=weeks)
    recent = history.loc[
        (history["stay_date"] > start) & (history["stay_date"] <= cutoff)
    ]
    means = recent.groupby(_weekday(recent["stay_date"]))["rate"].mean()
    keys = _weekday(targets["stay_date"])
    return pd.Series(means.reindex(keys).to_numpy(), index=targets.index, dtype=float)


def _weekday(stay_date: pd.Series) -> pd.Series:
    """Gives each night's weekday, Monday 0.

    Args:
        stay_date (pd.Series): The nights.

    Returns:
        pd.Series: Each night's weekday.
    """
    return pd.to_datetime(stay_date).dt.dayofweek.rename("weekday")
