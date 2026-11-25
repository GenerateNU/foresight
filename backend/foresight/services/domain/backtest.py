import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.services.domain.city import local_today
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.training_data import (
    TrainingData,
    combine_identical_rows,
    training_data,
)
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.baselines import recent_weekday_mean, same_weekday_last_year
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES, INPUT_GROUPS, LEAD

BASELINES = {
    "last_year": "Same weekday last year",
    "recent_weekday": "Last 4 weeks, same weekday",
}


def score(y_true: Any, y_pred: Any) -> dict[str, float]:
    """Scores predictions against the true values.

    Shared by models and the backtest's baselines, so both are measured alike.

    Args:
        y_true (Any): True target values, array-like.
        y_pred (Any): One prediction per true value, array-like.

    Returns:
        dict[str, float]: mae, rmse, mape (over nonzero true values only),
            r2 and bias (mean of predicted - true; positive means it
            predicts too high).
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    nonzero = y_true != 0
    mape = np.mean(np.abs((y_true - y_pred)[nonzero] / y_true[nonzero]))
    return {
        "mae": mean_absolute_error(y_true, y_pred),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mape": float(mape),
        "r2": r2_score(y_true, y_pred),
        "bias": float(np.mean(y_pred - y_true)),
    }


def in_feature_order(inputs: Sequence[str]) -> list[str]:
    """Orders inputs as FEATURES does, dropping repeats.

    Args:
        inputs (Sequence[str]): The inputs.

    Returns:
        list[str]: The inputs, in FEATURES order.
    """
    chosen = set(inputs)
    return [f for f in FEATURES if f in chosen]


@dataclass(frozen=True, slots=True)
class BaselineScore:
    """A baseline scored on the test nights it could predict, beside the model.

    Attributes:
        nights (int): Test rows the baseline had history for.
        metrics (dict[str, float]): As `BacktestResult.metrics`.
        model_mae (float): The model's MAE on those same rows.
        skill (float | None): 1 - model MAE / baseline MAE; above 0 means the
            model wins.
    """

    nights: int
    metrics: dict[str, float]
    model_mae: float
    skill: float | None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Each test row's actual and predicted rate, and how far off they were.

    Scores are per booked room, one row per room per night.

    Attributes:
        hotel_name (str): The hotel.
        inputs (list[str]): The features the model was trained on.
        event_days (int | None): Event history the model saw; None for all.
        rows (pd.DataFrame): stay_date, lead_days, actual and predicted; with
            baselines, one column per BASELINES key too (NaN without history).
        metrics (dict[str, float]): mae, rmse, mape, r2 and bias.
        baselines (dict[str, BaselineScore]): Keyed like BASELINES; empty if
            not asked for.
    """

    hotel_name: str
    inputs: list[str]
    event_days: int | None
    rows: pd.DataFrame
    metrics: dict[str, float]
    baselines: dict[str, BaselineScore]


@dataclass(frozen=True, slots=True)
class BacktestSplit:
    """A hotel's training rows, split at the cutoff; holds no session.

    Attributes:
        hotel_name (str): The hotel.
        data (TrainingData): Every row, from the loader training uses, so
            the backtest scores the model that would ship.
        cutoff (date): The last training night.
        seen (np.ndarray): True for training rows, False for test rows.
    """

    hotel_name: str
    data: TrainingData
    cutoff: date
    seen: np.ndarray


async def load_backtest(
    session: AsyncSession,
    hotel_id: int,
    *,
    test_days: int = 90,
    start: date | None = None,
) -> BacktestSplit:
    """Loads past training rows and splits them `test_days` before the newest.

    The database part of a backtest, which trains in memory on older nights
    as if trained that day and predicts the newest; `run_backtest` then needs
    no session, so the caller can release its connection before the fit.
    Nights run up to yesterday in the hotel's city.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        test_days (int): Nights to hold back for testing.
        start (date | None): First night; None for the first booked one.

    Returns:
        BacktestSplit: The rows and the split.

    Raises:
        NotFoundError: The hotel doesn't exist.
        InvalidRequestError: There are no nights on one side of the cutoff.
    """
    hotel = await get_hotel(session, hotel_id)
    yesterday = local_today(hotel.city) - timedelta(days=1)
    data = await training_data(session, hotel, start=start, end=yesterday)
    if data.rows.empty:
        raise InvalidRequestError("no priced nights to backtest")
    cutoff = data.rows["stay_date"].max() - timedelta(days=test_days)
    seen = (data.rows["stay_date"] <= cutoff).to_numpy()
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

    Scores one set of inputs; compare sets by running it once per set. The
    model is thrown away afterwards.

    Args:
        split (BacktestSplit): The rows, split.
        baselines (bool): Also score the BASELINES on the same nights.
        inputs (Sequence[str] | None): The features to train on; None for
            every input, like the model that's served.
        event_days (int | None): Event history the model may see before the
            cutoff; None for all.

    Returns:
        BacktestResult: The predictions and scores.

    Raises:
        InvalidRequestError: `event_days` is below 1.
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
    """Fits on the training rows and predicts the test rows.

    Args:
        split (BacktestSplit): The rows, split.
        columns (list[str]): The inputs to use.
        event_days (int | None): Event history to keep; None for all.

    Returns:
        np.ndarray: One prediction per test row.
    """
    x = split.data.x[columns]
    if event_days is not None:
        x = _limit_event_history(x, split, event_days)
    model = await _fit_seen(split.data, split.seen, x)
    return model.predict(x[~split.seen])


async def _fit_seen(data: TrainingData, seen: np.ndarray, x: pd.DataFrame) -> EBMModel:
    """Fits an EBM on the seen rows, weighted and merged as training is.

    CPU-bound for seconds, so it runs in a thread to keep the event loop free.

    Args:
        data (TrainingData): Every row.
        seen (np.ndarray): True for the rows to fit on.
        x (pd.DataFrame): The inputs to use, row for row with `data`.

    Returns:
        EBMModel: The fitted model.
    """
    xc, yc, wc, _ = combine_identical_rows(
        x[seen], data.y[seen], data.weights[seen], data.rows.loc[seen, "stay_date"]
    )
    model = EBMModel()
    await asyncio.to_thread(model.fit, xc, yc, sample_weight=wc)
    return model


def _limit_event_history(
    x: pd.DataFrame, split: BacktestSplit, event_days: int
) -> pd.DataFrame:
    """Blanks the event inputs on nights more than `event_days` before the cutoff.

    As if event history only reached that far back: the test nights and the
    other inputs are untouched, so runs with different `event_days` differ
    only in how much event history the model learned from.

    Args:
        x (pd.DataFrame): The inputs.
        split (BacktestSplit): The rows, split.
        event_days (int): Event history to keep.

    Returns:
        pd.DataFrame: A copy of the inputs, with old event inputs blank.
    """
    start = split.cutoff - timedelta(days=event_days)
    old = (split.data.rows["stay_date"] <= start).to_numpy()
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
    """Lists the test rows' actual and predicted rates, and the baselines'.

    A baseline predicts a night, so it's built from each training night's
    average booked rate, up to the cutoff as the model saw, and scored
    against every booked room on the test night, as the model is.

    Args:
        split (BacktestSplit): The rows, split.
        predicted (np.ndarray): The model's prediction per test row.
        baselines (bool): Add a column per baseline.

    Returns:
        pd.DataFrame: One row per test row.
    """
    rows, seen = split.data.rows, split.seen
    targets = rows.loc[~seen]
    result = pd.DataFrame(
        {
            "stay_date": targets["stay_date"],
            LEAD: split.data.x.loc[~seen, LEAD].to_numpy(),
            "actual": split.data.y[~seen],
            "predicted": predicted,
        }
    )
    if baselines:
        history = (
            rows.loc[seen]
            .assign(rate=split.data.y[seen])
            .groupby("stay_date", as_index=False)["rate"]
            .mean()
        )
        result["last_year"] = same_weekday_last_year(history, targets)
        result["recent_weekday"] = recent_weekday_mean(history, targets, split.cutoff)
    return result


def _score_baseline(nights: pd.DataFrame, column: str) -> BaselineScore:
    """Scores a baseline and the model on the rows the baseline could predict.

    Args:
        nights (pd.DataFrame): The test rows, with the baseline's column.
        column (str): The baseline.

    Returns:
        BaselineScore: Both scores.
    """
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
