"""Backtest the pricing model: train on older nights, predict the newest ones.

Read-only; models are trained in memory and thrown away. Trains on every
night except the last `test_days`, as if it were trained that day, then
predicts those nights. For a hotel that trains on bookings the rows are booked
rooms, one per room per night (decision 0056), so scores are per room. The
inputs come from `pricing_model.training_data`, the same loader training uses,
so the backtest scores the model that would ship.

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
from foresight.services.ml.features import FEATURES, INPUT_GROUPS, LEAD
from foresight.services.ml.weighting import combine_identical_rows

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    from sqlalchemy.ext.asyncio import AsyncSession

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
    """Each test row's actual and predicted rate, and how far off they were."""

    hotel_name: str
    target: str  # what was predicted: "adr_nett" (booked rooms) or "arr" (nights)
    inputs: list[str]  # the features the model was trained on
    event_days: int | None  # event history the model saw; None means all of it
    # One row per test night, or per booked room per night: stay_date,
    # room_type, actual, predicted, low, high (the (1 - ALPHA) interval);
    # lead_days on booked rooms; with baselines, also one column per BASELINES
    # key (NaN where it had no history)
    rows: pd.DataFrame
    metrics: dict[str, float | None]  # mae, rmse, mape, r2, bias, coverage
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
    yesterday = date.today() - timedelta(days=1)
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

    Raises InvalidRequestError if an input the training data doesn't have is
    asked for, or baselines are asked for on booked rooms.
    """
    if event_days is not None and event_days < 1:
        raise InvalidRequestError("--event-days must be at least 1")
    data = split.data
    have = list(data.x.columns)
    columns = in_feature_order(have if inputs is None else inputs)
    if missing := [c for c in columns if c not in have]:
        raise InvalidRequestError(
            f"no {', '.join(missing)} in this hotel's training data: "
            f"it trains on nights because {data.reason}"
        )
    if baselines and data.from_bookings:
        raise InvalidRequestError(
            "baselines compare nights, but this hotel trains on booked rooms"
        )
    predicted, low, high = await _fit_predict(split, columns, event_days)
    rows = _test_rows(split, predicted, low, high, baselines=baselines)
    return BacktestResult(
        hotel_name=split.hotel_name,
        target=data.target,
        inputs=columns,
        event_days=event_days,
        rows=rows,
        metrics=score(rows["actual"], rows["predicted"], low, high),
        baselines={
            name: _score_baseline(rows, name) for name in BASELINES if baselines
        },
    )


async def _fit_predict(
    split: BacktestSplit, columns: list[str], event_days: int | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fits on the training rows' `columns`; predicts the test rows.

    Rows the model can't tell apart are merged before the fit, as training
    does (decision 0056).
    """
    x = split.data.x[columns]
    if event_days is not None:
        x = _limit_event_history(x, split, event_days)
    seen = split.seen
    xc, yc, wc, _ = combine_identical_rows(
        x[seen],
        split.data.y[seen],
        split.data.weights[seen],
        split.data.nights.loc[seen, "stay_date"],
    )
    model = EBMModel(alpha=ALPHA, calibration_frac=HOLDOUT_FRAC)
    # CPU-bound for seconds; a thread keeps the event loop free.
    await asyncio.to_thread(model.fit, xc, yc, sample_weight=wc)
    return model.predict_interval(x[~seen])


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
    low: np.ndarray,
    high: np.ndarray,
    *,
    baselines: bool,
) -> pd.DataFrame:
    """The test rows' actual and predicted rates, and the baselines' if asked."""
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
    if split.data.from_bookings:
        result[LEAD] = split.data.x.loc[~seen, LEAD].to_numpy()
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
