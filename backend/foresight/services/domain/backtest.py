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
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import build_features
from foresight.services.ml.weighting import sample_weights, training_mask

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Each test night's actual and predicted rate, and how far off they were."""

    nights: pd.DataFrame  # stay_date, actual, predicted
    metrics: dict[str, float | None]  # mae, rmse, mape, r2, coverage


async def run_backtest(
    session: AsyncSession, hotel_id: int, *, test_days: int = 90
) -> BacktestResult:
    """Predicts the last `test_days` nights with a model trained on the rest.

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
    model = EBMModel(alpha=0.2, calibration_frac=HOLDOUT_FRAC)
    # CPU-bound for seconds; a thread keeps the event loop free.
    await asyncio.to_thread(model.fit, x[seen], y[seen], sample_weight=weights[seen])

    return BacktestResult(
        nights=pd.DataFrame(
            {
                "stay_date": nights.loc[~seen, "stay_date"],
                "actual": y[~seen],
                "predicted": model.predict(x[~seen]),
            }
        ),
        metrics=model.evaluate(x[~seen], y[~seen]),
    )
