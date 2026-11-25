"""Backtest the pricing model: train on older nights, predict the newest ones.

Read-only; models are trained in memory and thrown away. Trains on every
night except the last `test_days`, as if it were trained that day, then
predicts those nights. For a hotel that trains on bookings the rows are booked
rooms, one per room per night (decision 0056), so scores are per room. The
inputs come from `model.training_data`, the same loader training uses,
so the backtest scores the model that would ship.

`run_backtest` scores one set of inputs; compare sets by running it once per set.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from foresight.services.domain.city import local_today
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.training_data import (
    combine_identical_rows,
    training_data,
)
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.baselines import recent_weekday_mean, same_weekday_last_year
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES, INPUT_GROUPS, LEAD

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.services.domain.training_data import TrainingData

# Baselines the model is compared with: column in `nights` -> label.
BASELINES = {
    "last_year": "Same weekday last year",
    "recent_weekday": "Last 4 weeks, same weekday",
}


def score(y_true: Any, y_pred: Any) -> dict[str, float]:
    """Scores predictions against the true values.

    Shared by models and the backtest's baselines, so both are measured alike.

    Args:
        y_true (array-like): True target values.
        y_pred (array-like): One prediction per true value.

    Returns:
        dict[str, float]: mae, rmse, mape, r2 and bias (mean of
            predicted - true; positive means it predicts too high).
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    nonzero = y_true != 0  # MAPE is undefined where the true value is 0
    mape = np.mean(np.abs((y_true - y_pred)[nonzero] / y_true[nonzero]))

    return {
        "mae": mean_absolute_error(y_true, y_pred),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mape": float(mape),
        "r2": r2_score(y_true, y_pred),
        "bias": float(np.mean(y_pred - y_true)),
    }


def in_feature_order(inputs: Sequence[str]) -> list[str]:
    """The inputs, without repeats, in FEATURES order."""
    chosen = set(inputs)
    return [f for f in FEATURES if f in chosen]


@dataclass(frozen=True, slots=True)
class BaselineScore:
    """A baseline scored on the test nights it could predict, beside the model."""

    nights: int  # test nights the baseline had history for
    metrics: dict[str, float]  # as BacktestResult.metrics
    model_mae: float  # the model's MAE on those same nights
    skill: float | None  # 1 - model_mae / baseline mae; > 0 means the model wins


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Each test row's actual and predicted rate, and how far off they were."""

    hotel_name: str
    inputs: list[str]  # the features the model was trained on
    event_days: int | None  # event history the model saw; None means all of it
    # One row per booked room per night: stay_date, lead_days,
    # actual, predicted; with baselines, also one column per BASELINES key
    # (NaN where it had no history)
    rows: pd.DataFrame
    metrics: dict[str, float]  # mae, rmse, mape, r2, bias
    baselines: dict[str, BaselineScore]  # keyed like BASELINES; empty if not asked


@dataclass(frozen=True, slots=True)
class BacktestSplit:
    """A hotel's training rows, split at the cutoff. Holds no session."""

    hotel_name: str
    data: TrainingData
    cutoff: date
    seen: np.ndarray  # True for training rows, False for test rows


async def load_backtest(
    session: AsyncSession,
    hotel_id: int,
    *,
    test_days: int = 90,
    start: date | None = None,
) -> BacktestSplit:
    """Past training rows from `start`, split `test_days` before the newest.

    The database part of a backtest; `run_backtest` then needs none, so the
    caller can release its connection before the fit.

    Raises NotFoundError for an unknown hotel, and InvalidRequestError if
    there are no nights on one side of the cutoff.
    """
    hotel = await get_hotel(session, hotel_id)
    # Yesterday in the hotel's timezone, like every other "today".
    yesterday = local_today(hotel.city) - timedelta(days=1)
    data = await training_data(session, hotel, start=start, end=yesterday)
    if data.nights.empty:
        raise InvalidRequestError("no priced nights to backtest")
    cutoff = data.nights["stay_date"].max() - timedelta(days=test_days)
    seen = (data.nights["stay_date"] <= cutoff).to_numpy()
    if not seen.any():
        raise InvalidRequestError(
            f"no nights before the cutoff {cutoff}; use a smaller --test-days"
        )
    return BacktestSplit(hotel.name, data, cutoff, seen)


async def run_backtest(
    split: BacktestSplit,
    *,
    baselines: bool = False,
    inputs: Sequence[str] | None = None,
    event_days: int | None = None,
) -> BacktestResult:
    """Predicts the test rows with a model trained on the rest.

    `inputs` picks the features the model trains on; the default is every
    input the training data has, like the model that's served. With
    `baselines`, also scores the BASELINES on the same nights.

    Raises InvalidRequestError for a bad `event_days`.
    """
    if event_days is not None and event_days < 1:
        raise InvalidRequestError("--event-days must be at least 1")
    columns = in_feature_order(FEATURES if inputs is None else inputs)
    predicted = await _fit_predict(split, columns, event_days)
    rows = _test_rows(split, predicted, baselines=baselines)
    return BacktestResult(
        hotel_name=split.hotel_name,
        inputs=columns,
        event_days=event_days,
        rows=rows,
        metrics=score(rows["actual"], rows["predicted"]),
        baselines={
            name: _score_baseline(rows, name) for name in BASELINES if baselines
        },
    )


async def _fit_predict(
    split: BacktestSplit, columns: list[str], event_days: int | None = None
) -> np.ndarray:
    """Fits on the training rows' `columns`; predicts the test rows.

    Rows the model can't tell apart are merged before the fit, as training
    does (decision 0056).
    """
    x = split.data.x[columns]
    if event_days is not None:
        x = _limit_event_history(x, split, event_days)
    model = await _fit_seen(split.data, split.seen, x)
    return model.predict(x[~split.seen])


async def _fit_seen(data: TrainingData, seen: np.ndarray, x: pd.DataFrame) -> EBMModel:
    """An EBM fit on the `seen` rows of `x`, weighted and merged as training is."""
    xc, yc, wc, _ = combine_identical_rows(
        x[seen], data.y[seen], data.weights[seen], data.nights.loc[seen, "stay_date"]
    )
    model = EBMModel()
    # CPU-bound for seconds; a thread keeps the event loop free.
    await asyncio.to_thread(model.fit, xc, yc, sample_weight=wc)
    return model


def _limit_event_history(
    x: pd.DataFrame, split: BacktestSplit, event_days: int
) -> pd.DataFrame:
    """Blanks the event inputs on nights more than `event_days` before the cutoff.

    As if event history only reached that far back: the test nights and the
    other inputs are untouched, so runs with different `event_days` differ
    only in how much event history the model learned from.
    """
    start = split.cutoff - timedelta(days=event_days)
    old = (split.data.nights["stay_date"] <= start).to_numpy()
    columns = [c for c in INPUT_GROUPS["events"] if c in x.columns]
    x = x.copy()
    x.loc[old, columns] = float("nan")
    return x


def _test_rows(
    split: BacktestSplit,
    predicted: np.ndarray,
    *,
    baselines: bool,
) -> pd.DataFrame:
    """The test rows' actual and predicted rates, and the baselines' if asked.

    A baseline predicts a night, so it's built from each training night's
    average booked rate and scored against every booked room on the test
    night, as the model is (decision 0076).
    """
    nights, seen = split.data.nights, split.seen
    targets = nights.loc[~seen]
    result = pd.DataFrame(
        {
            "stay_date": targets["stay_date"],
            LEAD: split.data.x.loc[~seen, LEAD].to_numpy(),
            "actual": split.data.y[~seen],
            "predicted": predicted,
        }
    )
    if baselines:
        # Baselines see only nights up to the cutoff, as the model did.
        history = (
            nights.loc[seen]
            .assign(rate=split.data.y[seen])
            .groupby("stay_date", as_index=False)["rate"]
            .mean()
        )
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
