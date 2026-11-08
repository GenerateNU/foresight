"""Daily tune-up: correct the active model with the manager's rates, no full retrain.

The active model is left as it is; a small EBM learns the gap between its
predictions and the rates the manager chose, and the two are saved together
as a new version (decision 0051). A tune-up always starts from the active
model's base, so corrections are rebuilt each time, never stacked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING

import pandas as pd

from foresight.repository import feedback as feedback_repo
from foresight.repository import pricing_model as model_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import (
    NO_FLIGHTS,
    events_for,
    hotel_location,
    weather_for,
)
from foresight.services.domain.pricing_model import LIBS
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel, TunedEBMModel
from foresight.services.ml.features import FEATURES, build_features

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.pricing_model import PricingModel

ALGORITHM = "ebm-tuned"
# Fewer manager rates than this and the tune-up is skipped.
MIN_TUNE_NIGHTS = 5


@dataclass(frozen=True, slots=True)
class TuneResult:
    model: PricingModel | None  # None when skipped
    activated: bool
    nights_used: int  # manager rates the correction learned from
    skipped: str | None = None  # why nothing was saved


async def check_tunable(session: AsyncSession, hotel_id: int) -> Hotel:
    """Fail fast, before a job is queued, if there's no model to tune.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: The hotel has no active model.
    """
    hotel = await get_hotel(session, hotel_id)
    if await model_repo.get_active_pricing_model(session, hotel.id) is None:
        raise InvalidRequestError("the hotel has no active model; train one first")
    return hotel


async def tune(session: AsyncSession, hotel: Hotel, *, activate: bool) -> TuneResult:
    """Correct the active model with the manager's current rates. Does not commit.

    Skips, saving nothing, if there are fewer than MIN_TUNE_NIGHTS rates.

    Raises:
        InvalidRequestError: The hotel has no active model.
    """
    active = await model_repo.get_active_pricing_model(session, hotel.id)
    if active is None:
        raise InvalidRequestError("the hotel has no active model; train one first")

    rows = await feedback_repo.tuning_feedback(session, hotel.id)
    if len(rows) < MIN_TUNE_NIGHTS:
        return TuneResult(
            None,
            False,
            len(rows),
            f"{len(rows)} manager rates; need at least {MIN_TUNE_NIGHTS}",
        )
    feedback = pd.DataFrame(rows)
    x = await _features(session, hotel, feedback)
    y = feedback["rate"].astype(float)

    # Tuning a tuned version starts again from its base (TunedEBMModel).
    base_id = active.metrics.get("base_model_id", active.id)
    base_row = active if base_id == active.id else await _model(session, base_id)
    artifact = await model_repo.get_artifact(session, active.id)
    if artifact is None:
        raise NotFoundError("Pricing model", active.id)
    base = EBMModel.from_bytes(artifact)

    # CPU-bound; a thread keeps the API answering meanwhile.
    model = await asyncio.to_thread(TunedEBMModel(base).fit, x, y)
    correction = model.correction(x)

    saved = await model_repo.create_pricing_model(
        session,
        hotel_id=hotel.id,
        algorithm=ALGORITHM,
        description=f"Tune-up of v{base_row.version} on {len(feedback)} manager rates",
        artifact=model.to_bytes(),
        features=FEATURES,
        metrics={
            "base_model_id": base_row.id,
            "base_version": base_row.version,
            "tune_nights": len(feedback),
            "mean_correction": round(float(correction.mean()), 2),
            # The interval served is the base's.
            "interval_level": base_row.metrics.get("interval_level"),
            "interval_margin": base_row.metrics.get("interval_margin"),
        },
        lib_versions={lib: version(lib) for lib in LIBS},
        data_start=min(base_row.data_start, feedback["stay_date"].min()),
        data_end=max(base_row.data_end, feedback["stay_date"].max()),
    )
    await model_repo.link_feedback(
        session,
        saved.id,
        [
            {
                "feedback_id": int(row["id"]),
                "rate_replaced": True,
                "weight_factor": 1.0,
                "training_rate": float(row["rate"]),
            }
            for row in rows
        ],
    )
    if activate:
        activated = await model_repo.activate_pricing_model(session, saved.id)
        assert activated is not None  # saved just above, in this transaction
        saved = activated
    return TuneResult(saved, activate, len(feedback))


async def _model(session: AsyncSession, model_id: int) -> PricingModel:
    model = await model_repo.get_pricing_model(session, model_id)
    if model is None:
        raise NotFoundError("Pricing model", model_id)
    return model


async def _features(
    session: AsyncSession, hotel: Hotel, feedback: pd.DataFrame
) -> pd.DataFrame:
    """The model's inputs for each night the manager priced, row for row.

    Built as recommendations build them, so past and future nights both work:
    weather falls back to the forecast, then typical weather.
    """
    days = sorted(set(feedback["stay_date"]))
    weather = await weather_for(session, hotel.city, days, fallback=True)
    events = await events_for(session, hotel.city, days)
    x = build_features(
        feedback[["stay_date", "room_type"]],
        events.frame,
        weather.frame,
        NO_FLIGHTS,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
    )
    return x[FEATURES]
