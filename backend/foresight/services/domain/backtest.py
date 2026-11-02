"""Backtest the pricing model: train on older nights, predict the newest ones.

Read-only; models are trained in memory and thrown away. Trains on every
night except the last `test_days`, as if it were trained that day, then
predicts those nights. The inputs come from `pricing_model.training_data`, the
same loader training uses, so the backtest scores the model that would ship.

`run_backtest` scores one set of inputs; compare sets by running it once per set.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.pricing_model import HOLDOUT_FRAC, training_data
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.base import score
from foresight.services.ml.baselines import recent_weekday_mean, same_weekday_last_year
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.services.domain.pricing_model import TrainingData

# The model's prediction interval is (1 - ALPHA); `coverage` is scored against it.
ALPHA = 0.2

# Baselines the model is compared with: column in `nights` -> label.
BASELINES = {
    "last_year": "Same weekday last year",
    "recent_weekday": "Last 4 weeks, same weekday",
}


def in_feature_order(inputs: Sequence[str]) -> list[str]:
    """The inputs, without repeats, in FEATURES order."""
    chosen = set(inputs)
    return [f for f in FEATURES if f in chosen]


@dataclass(frozen=True, slots=True)
class BaselineScore:
    """A baseline scored on the test nights it could predict, beside the model."""

    nights: int  # test nights the baseline had history for
    metrics: dict[str, float | None]  # as BacktestResult.metrics; no coverage
    model_mae: float  # the model's MAE on those same nights
    skill: float | None  # 1 - model_mae / baseline mae; > 0 means the model wins


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Each test night's actual and predicted rate, and how far off they were."""

    hotel_name: str
    inputs: list[str]  # the features the model was trained on
    # stay_date, room_type, actual, predicted, low, high (the (1 - ALPHA)
    # interval); with baselines, also one column per BASELINES key (NaN where
    # it had no history)
    nights: pd.DataFrame
    metrics: dict[str, float | None]  # mae, rmse, mape, r2, bias, coverage
    baselines: dict[str, BaselineScore]  # keyed like BASELINES; empty if not asked


@dataclass(frozen=True, slots=True)
class _Split:
    data: TrainingData
    cutoff: date
    seen: np.ndarray  # True for training nights, False for test nights


async def run_backtest(
    session: AsyncSession,
    hotel_id: int,
    *,
    test_days: int = 90,
    baselines: bool = False,
    inputs: Sequence[str] = FEATURES,
) -> BacktestResult:
    """Predicts the last `test_days` nights with a model trained on the rest.

    `inputs` picks the features the model trains on; the default is every
    feature, like the model that's served. With `baselines`, also scores the
    BASELINES on the same nights.

    Raises NotFoundError for an unknown hotel, and InvalidRequestError if
    there are no nights on one side of the cutoff.
    """
    hotel = await get_hotel(session, hotel_id)
    split = await _split(session, hotel, test_days)
    columns = in_feature_order(inputs)
    predicted, low, high = await _fit_predict(split, columns)
    nights = _test_nights(split, predicted, low, high, baselines=baselines)
    return BacktestResult(
        hotel_name=hotel.name,
        inputs=columns,
        nights=nights,
        metrics=score(nights["actual"], nights["predicted"], low, high),
        baselines={
            name: _score_baseline(nights, name) for name in BASELINES if baselines
        },
    )


async def _split(session: AsyncSession, hotel: Hotel, test_days: int) -> _Split:
    """Every past priced night, split at `test_days` before the newest one."""
    yesterday = date.today() - timedelta(days=1)
    data = await training_data(session, hotel, start=None, end=yesterday)
    if data.nights.empty:
        raise InvalidRequestError("no priced nights to backtest")
    cutoff = data.nights["stay_date"].max() - timedelta(days=test_days)
    seen = (data.nights["stay_date"] <= cutoff).to_numpy()
    if not seen.any():
        raise InvalidRequestError(
            f"no nights before the cutoff {cutoff}; use a smaller --test-days"
        )
    return _Split(data, cutoff, seen)


async def _fit_predict(
    split: _Split, columns: list[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fits on the training nights' `columns`; predicts the test nights."""
    x = split.data.x[columns]
    seen = split.seen
    model = EBMModel(alpha=ALPHA, calibration_frac=HOLDOUT_FRAC)
    # CPU-bound for seconds; a thread keeps the event loop free.
    await asyncio.to_thread(
        model.fit, x[seen], split.data.y[seen], sample_weight=split.data.weights[seen]
    )
    return model.predict_interval(x[~seen])


def _test_nights(
    split: _Split,
    predicted: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    *,
    baselines: bool,
) -> pd.DataFrame:
    """The test nights' actual and predicted rates, and the baselines' if asked."""
    nights, seen = split.data.nights, split.seen
    history, targets = nights.loc[seen], nights.loc[~seen]
    result = pd.DataFrame(
        {
            "stay_date": targets["stay_date"],
            "room_type": targets["room_type"],
            "actual": split.data.y[~seen],
            "predicted": predicted,
            "low": low,
            "high": high,
        }
    )
    if baselines:
        # Baselines see only nights up to the cutoff, as the model did.
        result["last_year"] = same_weekday_last_year(history, targets)
        result["recent_weekday"] = recent_weekday_mean(history, targets, split.cutoff)
    return result


def _score_baseline(nights: pd.DataFrame, column: str) -> BaselineScore:
    """Scores a baseline and the model on the nights the baseline could predict."""
    covered = nights.loc[nights[column].notna()]
    if covered.empty:
        return BaselineScore(nights=0, metrics={}, model_mae=float("nan"), skill=None)
    metrics = score(covered["actual"], covered[column])
    model_mae = score(covered["actual"], covered["predicted"])["mae"]
    assert model_mae is not None and metrics["mae"] is not None
    skill = 1 - model_mae / metrics["mae"] if metrics["mae"] > 0 else None
    return BaselineScore(
        nights=len(covered), metrics=metrics, model_mae=model_mae, skill=skill
    )
