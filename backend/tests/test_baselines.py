"""The backtest's baselines and the shared scoring. No database: pure pandas."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from foresight.services.ml.base import Model, score
from foresight.services.ml.baselines import recent_weekday_mean, same_weekday_last_year


def _nights(rows: list[tuple[date, str, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=pd.Index(["stay_date", "room_type", "rate"]))


def test_last_year_matches_weekday_and_room_type() -> None:
    night = date(2026, 6, 10)  # a Wednesday
    history = _nights(
        [
            (night - timedelta(days=364), "Double", 120.0),
            (night - timedelta(days=364), "Suite", 300.0),
            # A year by calendar date lands on another weekday; not used.
            (night - timedelta(days=365), "Double", 999.0),
        ]
    )
    targets = _nights([(night, "Double", None), (night, "Suite", None)])

    got = same_weekday_last_year(history, targets)

    assert (night - timedelta(days=364)).weekday() == night.weekday()
    assert got.tolist() == [120.0, 300.0]
    assert got.index.equals(targets.index)


def test_last_year_is_nan_without_history() -> None:
    history = _nights([(date(2025, 6, 11), "Double", 120.0)])
    targets = _nights([(date(2026, 6, 10), "Twin", None)])

    assert same_weekday_last_year(history, targets).isna().all()


def test_recent_weekday_mean_uses_only_the_weeks_before_cutoff() -> None:
    cutoff = date(2026, 6, 30)  # a Tuesday
    mondays = [cutoff - timedelta(days=1 + 7 * k) for k in range(6)]
    history = _nights(
        [
            (mondays[0], "Double", 100.0),
            (mondays[1], "Double", 110.0),
            (mondays[2], "Double", 120.0),
            (mondays[3], "Double", 130.0),
            (mondays[4], "Double", 999.0),  # more than 4 weeks before cutoff
            (cutoff + timedelta(days=6), "Double", 999.0),  # after cutoff: leakage
        ]
    )
    targets = _nights([(cutoff + timedelta(days=13), "Double", None)])  # a Monday

    got = recent_weekday_mean(history, targets, cutoff)

    assert got.tolist() == [pytest.approx(115.0)]


def test_recent_weekday_mean_keeps_weekdays_and_room_types_apart() -> None:
    cutoff = date(2026, 6, 30)
    history = _nights(
        [
            (date(2026, 6, 29), "Double", 100.0),  # Monday
            (date(2026, 6, 27), "Double", 200.0),  # Saturday
            (date(2026, 6, 29), "Suite", 400.0),
        ]
    )
    targets = _nights(
        [
            (date(2026, 7, 6), "Double", None),  # Monday
            (date(2026, 7, 4), "Double", None),  # Saturday
            (date(2026, 7, 6), "Suite", None),
            (date(2026, 7, 7), "Double", None),  # Tuesday: no history
        ]
    )

    got = recent_weekday_mean(history, targets, cutoff)

    assert got.iloc[:3].tolist() == [100.0, 200.0, 400.0]
    assert np.isnan(got.iloc[3])


class _Fixed(Model):
    """A model that returns preset predictions and intervals."""

    def __init__(self, pred: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> None:
        super().__init__()
        self._pred, self._lo, self._hi = pred, lo, hi

    def fit(self, x: pd.DataFrame, y: pd.Series) -> _Fixed:
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self._pred

    def predict_interval(self, x: pd.DataFrame, alpha: float = 0.05):
        return self._pred, self._lo, self._hi


def test_evaluate_is_score_of_its_predictions() -> None:
    y = pd.Series([100.0, 150.0, 200.0])
    pred = np.array([110.0, 140.0, 230.0])
    lo, hi = pred - 15, pred + 15
    model = _Fixed(pred, lo, hi)
    x = pd.DataFrame(index=y.index)

    got = model.evaluate(x, y)

    assert got == score(y, pred, lo, hi)
    assert got["mae"] == pytest.approx(50 / 3)
    assert got["bias"] == pytest.approx(10.0)
    assert got["coverage"] == pytest.approx(2 / 3)
    assert score(y, pred)["coverage"] is None
