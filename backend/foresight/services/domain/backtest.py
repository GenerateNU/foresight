"""Backtest the pricing model: train on older nights, predict the newest ones.

Read-only; the model is trained in memory and thrown away. Trains on every
night except the last `test_days`, as if it were trained that day, then
predicts those nights.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from foresight.repository import hotel as hotel_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import NO_EVENTS, NO_FLIGHTS, weather_for
from foresight.services.domain.pricing_model import _NIGHT_COLUMNS, HOLDOUT_FRAC
from foresight.services.ml.base import score
from foresight.services.ml.baselines import recent_weekday_mean, same_weekday_last_year
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import build_features
from foresight.services.ml.weighting import sample_weights, training_mask

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# The model's prediction interval is (1 - ALPHA); `coverage` is scored against it.
ALPHA = 0.2


# Baselines the model is compared with: column in `nights` -> label.
BASELINES = {
    "last_year": "Same weekday last year",
    "recent_weekday": "Last 4 weeks, same weekday",
}


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
    # stay_date, room_type, actual, predicted, low, high (the (1 - ALPHA)
    # interval); with baselines, also one column per BASELINES key (NaN where
    # it had no history)
    nights: pd.DataFrame
    metrics: dict[str, float | None]  # mae, rmse, mape, r2, bias, coverage
    baselines: dict[str, BaselineScore]  # keyed like BASELINES; empty if not asked


async def run_backtest(
    session: AsyncSession,
    hotel_id: int,
    *,
    test_days: int = 90,
    baselines: bool = False,
) -> BacktestResult:
    """Predicts the last `test_days` nights with a model trained on the rest.

    With `baselines`, also scores the BASELINES on the same nights, so the
    model can be judged against the simple guesses it has to beat.

    Raises NotFoundError for an unknown hotel.
    """
    hotel = await get_hotel(session, hotel_id)

    # Every past night, prepared how pricing_model.train() prepares it.
    yesterday = date.today() - timedelta(days=1)
    rows = await hotel_repo.training_nights(
        session, hotel.id, start=None, end=yesterday
    )
    nights = pd.DataFrame(rows, columns=pd.Index(_NIGHT_COLUMNS))
    nights["rate"] = pd.Series(nights["rate"], dtype=float)
    nights = nights.loc[training_mask(nights["rate"])].reset_index(drop=True)

    days = sorted(set(nights["stay_date"]))
    weather = await weather_for(session, hotel.city, days, fallback=False)
    x = build_features(nights, NO_EVENTS, weather.frame, NO_FLIGHTS)
    y = nights["rate"]
    weights = sample_weights(
        (nights["rooms_sold"] / nights["rooms_available"]).clip(0, 1)
    )

    # Train on nights up to the cutoff, test on the ones after it.
    cutoff = nights["stay_date"].max() - timedelta(days=test_days)
    seen = (nights["stay_date"] <= cutoff).to_numpy()
    model = EBMModel(alpha=ALPHA, calibration_frac=HOLDOUT_FRAC)
    # CPU-bound for seconds; a thread keeps the event loop free.
    await asyncio.to_thread(model.fit, x[seen], y[seen], sample_weight=weights[seen])

    predicted, low, high = model.predict_interval(x[~seen])
    history, targets = nights.loc[seen], nights.loc[~seen]
    result = pd.DataFrame(
        {
            "stay_date": targets["stay_date"],
            "room_type": targets["room_type"],
            "actual": y[~seen],
            "predicted": predicted,
            "low": low,
            "high": high,
        }
    )
    if baselines:
        # Baselines see only nights up to the cutoff, as the model did.
        result["last_year"] = same_weekday_last_year(history, targets)
        result["recent_weekday"] = recent_weekday_mean(history, targets, cutoff)
    return BacktestResult(
        hotel_name=hotel.name,
        nights=result,
        metrics=score(result["actual"], result["predicted"], low, high),
        baselines={
            name: _score_baseline(result, name) for name in BASELINES if baselines
        },
    )


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
