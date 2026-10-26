"""Pricing models: train a new version for a hotel, and read the versions.

Training only reads what's already ingested (performance and weather); it
never fetches. Every run makes a new version, so earlier ones stay to compare
against. Activation follows decision 0009: a new version is saved inactive and
becomes the hotel's active one only once training succeeded, unless the caller
asks to keep the current one serving.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import (
    NO_EVENTS,
    NO_FLIGHTS,
    weather_for,
)
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES, build_features
from foresight.services.ml.weighting import sample_weights, training_mask

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.pricing_model import PricingModel

ALGORITHM = "ebm"
# EBM needs enough rows for its own validation split plus our calibration set.
MIN_TRAINING_NIGHTS = 120
# Share of the most recent nights scored after training; also the conformal
# calibration share (decision 0005), so metrics describe unseen nights.
HOLDOUT_FRAC = 0.15
_NIGHT_COLUMNS = ["stay_date", "room_type", "rate", "rooms_sold", "rooms_available"]
_LIBS = ("interpret-core", "scikit-learn", "numpy", "pandas", "joblib")


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: PricingModel
    activated: bool
    seconds: float
    nights_used: int


async def check_trainable(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> Hotel:
    """Fail fast, before a job is queued, if training can't run.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: start is after end, or no nights are loaded in
            the window.
    """
    hotel = await get_hotel(session, hotel_id)
    if start is not None and end is not None and start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    loaded = await hotel_repo.stay_date_range(session, hotel.id)
    if loaded is None:
        raise InvalidRequestError(
            "no nights are loaded for this hotel; ingest performance first"
        )
    first, last = loaded
    if (start is not None and start > last) or (end is not None and end < first):
        raise InvalidRequestError(
            f"no nights in the window; loaded nights run {first} to {last}"
        )
    return hotel


async def train(
    session: AsyncSession,
    hotel: Hotel,
    *,
    description: str | None,
    start: date | None,
    end: date | None,
    activate: bool,
    params: dict[str, Any],
) -> TrainingResult:
    """Train, score and save a new version. Does not commit.

    `params` go to the EBM as-is (e.g. {"interactions": 0}); the job validated
    them. Raises InvalidRequestError if too few nights are left to train on.
    """
    began = time.monotonic()
    rows = await hotel_repo.training_nights(session, hotel.id, start=start, end=end)
    nights = pd.DataFrame(rows, columns=pd.Index(_NIGHT_COLUMNS))
    # Rates arrive as Decimal or None; None becomes NaN.
    rate = pd.Series(nights["rate"], dtype=float)
    nights["rate"] = rate

    # Decision 0004: free/staff/unpriced nights go before features and weights,
    # so all three line up row for row.
    keep = training_mask(rate)
    nights = nights.loc[keep].reset_index(drop=True)
    if len(nights) < MIN_TRAINING_NIGHTS:
        raise InvalidRequestError(
            f"{len(nights)} priced nights to train on; need at least "
            f"{MIN_TRAINING_NIGHTS}"
        )

    days = sorted(set(nights["stay_date"]))
    weather = await weather_for(session, hotel.city, days, fallback=False)
    x = build_features(nights, NO_EVENTS, weather.frame, NO_FLIGHTS)
    y = nights["rate"]
    occupancy = nights["rooms_sold"] / nights["rooms_available"]
    weights = sample_weights(occupancy.clip(0, 1))

    # CPU-bound for seconds; a thread keeps the API answering meanwhile.
    metrics, artifact = await asyncio.to_thread(_fit, x, y, weights, nights, params)

    saved = await model_repo.create_pricing_model(
        session,
        hotel_id=hotel.id,
        algorithm=ALGORITHM,
        description=description,
        artifact=artifact,
        features=FEATURES,
        metrics=metrics,
        lib_versions={lib: version(lib) for lib in _LIBS},
        data_start=nights["stay_date"].min(),
        data_end=nights["stay_date"].max(),
    )
    if activate:
        activated = await model_repo.activate_pricing_model(session, saved.id)
        assert activated is not None  # saved just above, in this transaction
        saved = activated
    return TrainingResult(
        saved, activate, round(time.monotonic() - began, 1), len(nights)
    )


async def list_models(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[PricingModel], int]:
    await get_hotel(session, hotel_id)
    return await model_repo.list_pricing_models(
        session, hotel_id, limit=limit, offset=offset
    )


async def get_model(session: AsyncSession, model_id: int) -> PricingModel:
    """Raises NotFoundError for an unknown model."""
    model = await model_repo.get_pricing_model(session, model_id)
    if model is None:
        raise NotFoundError("Pricing model", model_id)
    return model


async def activate_model(session: AsyncSession, model_id: int) -> PricingModel:
    """Make this version the one its hotel serves. Raises NotFoundError."""
    await get_model(session, model_id)
    model = await model_repo.activate_pricing_model(session, model_id)
    assert model is not None
    return model


def _fit(
    x: pd.DataFrame,
    y: pd.Series,
    weights: np.ndarray,
    nights: pd.DataFrame,
    params: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    """Fit, score on the held-out nights, and serialize. Returns the metrics
    and the artifact to store."""
    model = EBMModel(alpha=0.2, calibration_frac=HOLDOUT_FRAC, **params).fit(
        x, y, sample_weight=weights
    )
    cut = int(len(x) * (1 - HOLDOUT_FRAC))
    metrics = _metrics(model, x.iloc[cut:], y.iloc[cut:], nights.iloc[cut:])
    return metrics, model.to_bytes()


def _metrics(
    model: EBMModel, x: pd.DataFrame, y: pd.Series, nights: pd.DataFrame
) -> dict[str, Any]:
    """Scores on the most recent nights; these also calibrated the interval."""
    scores = model.evaluate(x, y)
    return {
        **{k: (None if v is None else round(float(v), 4)) for k, v in scores.items()},
        "interval_level": 1 - model.alpha,
        "interval_margin": round(model.interval_margin(model.alpha), 2),
        "holdout_nights": len(x),
        "holdout_start": nights["stay_date"].min().isoformat(),
        "holdout_end": nights["stay_date"].max().isoformat(),
        "mean_rate": round(float(np.mean(y)), 2),
    }
