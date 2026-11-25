"""Pricing models: train a new version for a hotel, and read the versions.

Training only reads what's already ingested (bookings and events); it never
fetches. Every run makes a new version, so earlier ones stay
to compare against. Activation follows decision 0009: a new version is saved
inactive and becomes the hotel's active one only once training succeeded,
unless the caller asks to keep the current one serving.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import numpy as np

from foresight.repository import hotel as hotel_repo
from foresight.repository import model as model_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.training_data import (
    MAIN_RATE_PLAN,
    MAIN_ROOM_CODE,
    TrainingData,
    combine_identical_rows,
    main_night_range,
    training_data,
    with_manager_rows,
)
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel, TunedEBMModel
from foresight.services.ml.resources import measure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    import pandas as pd
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.model import PricingModel

ALGORITHM = "ebm"
# Fewest booked rooms to train on (decision 0076); EBM holds some back for its
# own early stopping.
MIN_TRAINING_ROWS = 120
# What every version learns to predict, stored in its metrics as `target`: each
# booked room's rate per night before VAT (decisions 0056, 0076).
TARGET = "adr_nett"
LIBS = ("interpret-core", "scikit-learn", "numpy", "pandas", "joblib")


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: PricingModel
    activated: bool
    seconds: float
    training_rows: int  # booked rooms plus manager rows
    training_nights: int  # distinct nights among them


async def check_trainable(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> Hotel:
    """Fail fast, before a job is queued, if training can't run.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: start is after end, or no booked nights of the
            main product fall in the window.
    """
    hotel = await get_hotel(session, hotel_id)
    if start is not None and end is not None and start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    loaded = await main_night_range(session, hotel)
    if loaded is None:
        raise InvalidRequestError(
            f"no {MAIN_ROOM_CODE} {MAIN_RATE_PLAN} bookings are loaded for this "
            "hotel; upload reservations first"
        )
    first, last = loaded
    if (start is not None and start > last) or (end is not None and end < first):
        raise InvalidRequestError(
            f"no booked nights in the window; bookings run {first} to {last}"
        )
    return hotel


@dataclass(frozen=True, slots=True)
class PreparedTraining:
    """Everything a fit needs, loaded and with feedback applied; no session."""

    data: TrainingData  # booked rooms plus manager rows
    feedback_nights: int  # manager rates added as rows
    began: float  # time.monotonic() when loading started


async def prepare_training(
    session: AsyncSession, hotel: Hotel, *, start: date | None, end: date | None
) -> PreparedTraining:
    """Load the training rows and apply the manager's feedback.

    The first of three steps (prepare, `fit`, `save_version`), so the caller
    can release its database connection while the model fits.

    Raises InvalidRequestError if too few rows are left to train on.
    """
    began = time.monotonic()
    data = await training_data(session, hotel, start=start, end=end)
    nights = data.nights
    if len(nights) < MIN_TRAINING_ROWS:
        raise InvalidRequestError(
            f"{len(nights)} booked rooms to train on; need at least {MIN_TRAINING_ROWS}"
        )

    data, feedback_nights = await with_manager_rows(
        session, hotel, data, start=start, end=end
    )
    return PreparedTraining(data, feedback_nights, began)


async def fit(
    prepared: PreparedTraining, params: dict[str, Any]
) -> tuple[dict[str, Any], bytes]:
    """Fit a model on every prepared row; returns its metrics and artifact.

    Needs no database. CPU-bound for seconds to minutes, so it runs in a
    thread to keep the API answering.
    """
    data = prepared.data
    metrics, artifact = await asyncio.to_thread(
        _fit, data.x, data.y, data.weights, data.nights, params
    )
    metrics["target"] = TARGET
    metrics["training_rows"] = len(data.nights)
    metrics["training_nights"] = int(data.nights["stay_date"].nunique())
    metrics["feedback_nights"] = prepared.feedback_nights
    metrics["one_off_nights"] = data.one_off_dropped
    return metrics, artifact


async def save_version(
    session: AsyncSession,
    hotel: Hotel,
    prepared: PreparedTraining,
    metrics: dict[str, Any],
    artifact: bytes,
    *,
    description: str | None,
    activate: bool,
) -> TrainingResult:
    """Save the fitted model as a new version, and activate it unless told not
    to. Creates the main room type the first time (decision 0079). Does not
    commit."""
    nights = prepared.data.nights
    room_type = await hotel_repo.get_or_create_room_type(
        session, hotel_id=hotel.id, name=MAIN_ROOM_CODE
    )
    saved = await model_repo.create_model(
        session,
        hotel_id=hotel.id,
        algorithm=ALGORITHM,
        description=description,
        artifact=artifact,
        features=list(prepared.data.x.columns),
        metrics=metrics,
        lib_versions={lib: version(lib) for lib in LIBS},
        data_start=nights["stay_date"].min(),
        data_end=nights["stay_date"].max(),
        room_type_id=room_type.id,
    )
    if activate:
        activated = await model_repo.activate_model(session, saved.id)
        assert activated is not None  # saved just above, in this transaction
        saved = activated
    return TrainingResult(
        saved,
        activate,
        round(time.monotonic() - prepared.began, 1),
        len(nights),
        metrics["training_nights"],
    )


async def list_models(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[PricingModel], int]:
    await get_hotel(session, hotel_id)
    return await model_repo.list_models(session, hotel_id, limit=limit, offset=offset)


async def get_model(session: AsyncSession, model_id: int) -> PricingModel:
    """Raises NotFoundError for an unknown model."""
    model = await model_repo.get_model(session, model_id)
    if model is None:
        raise NotFoundError("Pricing model", model_id)
    return model


async def load_model(session: AsyncSession, stored: PricingModel) -> EBMModel:
    """The version's trained model, ready to predict.

    A tune-up's artifact holds only its correction, so its base version's
    artifact is loaded too and joined to it (decision 0078).

    Raises:
        NotFoundError: The version or its base has no artifact.
    """
    model = EBMModel.from_bytes(await _artifact(session, stored.id))
    if stored.base_model_id is None:
        return model
    if not isinstance(model, TunedEBMModel):
        raise TypeError(f"pricing model {stored.id} has a base but isn't a tune-up")
    base = EBMModel.from_bytes(await _artifact(session, stored.base_model_id))
    return model.attach_base(base)


async def _artifact(session: AsyncSession, model_id: int) -> bytes:
    artifact = await model_repo.get_artifact(session, model_id)
    if artifact is None:
        raise NotFoundError("Pricing model", model_id)
    return artifact


async def activate_model(session: AsyncSession, model_id: int) -> PricingModel:
    """Make this version the one its hotel serves. Raises NotFoundError."""
    await get_model(session, model_id)
    model = await model_repo.activate_model(session, model_id)
    assert model is not None
    return model


def _fit(
    x: pd.DataFrame,
    y: pd.Series,
    weights: np.ndarray,
    nights: pd.DataFrame,
    params: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    """Fit on every row and serialize (decision 0085). Returns the fit's time
    and memory as metrics, and the artifact to store.

    Rows the model can't tell apart are merged first (decision 0056), so booked
    rooms fit in a fraction of the time. Accuracy isn't scored here: the
    model has seen every row, so the backtest is where it's measured.
    """
    xc, yc, wc, _ = combine_identical_rows(x, y, weights, nights["stay_date"])
    with measure() as cost:
        model = EBMModel(**params).fit(xc, yc, sample_weight=wc)
    return {**cost, "mean_rate": round(float(np.mean(y)), 2)}, model.to_bytes()
