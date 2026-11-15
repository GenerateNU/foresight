"""Daily tune-up: correct the active model with the manager's rates, no full retrain.

The active model is left as it is; a small EBM learns the gap between its
predictions and the rates the manager chose, and the two are saved together
as a new version (decision 0057). A tune-up always starts from the active
model's base, so corrections are rebuilt each time, never stacked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from importlib.metadata import version
from typing import TYPE_CHECKING

import pandas as pd

from foresight.repository import feedback as feedback_repo
from foresight.repository import pricing_model as model_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain.city import local_today
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import events_for, hotel_location
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
# Nights the manager left alone teach the correction "no change here": every
# night with a snapshot this many days back and ahead (decision 0060).
UNTOUCHED_DAYS = 30


@dataclass(frozen=True, slots=True)
class TuneResult:
    model: PricingModel | None  # None when skipped
    activated: bool
    nights_used: int  # manager rates the correction learned from
    untouched_used: int = 0  # nights left alone, learned as "no change"
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
            skipped=f"{len(rows)} manager rates; need at least {MIN_TUNE_NIGHTS}",
        )
    feedback = pd.DataFrame(rows)
    untouched = await _untouched(session, hotel, active, feedback)

    # Tuning a tuned version starts again from its base (TunedEBMModel).
    base_id = active.metrics.get("base_model_id", active.id)
    base_row = active if base_id == active.id else await _model(session, base_id)
    artifact = await model_repo.get_artifact(session, active.id)
    if artifact is None:
        raise NotFoundError("Pricing model", active.id)
    base = EBMModel.from_bytes(artifact)

    # The manager's nights first, then the nights they left alone, whose
    # target is the base's own prediction (a gap of 0).
    both = pd.concat(
        [feedback[["stay_date", "room_type"]], untouched], ignore_index=True
    )
    x = await _features(session, hotel, both)
    x_manager = x.iloc[: len(feedback)]
    y = pd.concat(
        [
            feedback["rate"].astype(float),
            pd.Series(base.predict(x.iloc[len(feedback) :]), dtype=float),
        ],
        ignore_index=True,
    )

    # CPU-bound; a thread keeps the API answering meanwhile.
    model = await asyncio.to_thread(TunedEBMModel(base).fit, x, y)
    correction = model.correction(x_manager)

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
            "untouched_nights": len(untouched),
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
    return TuneResult(saved, activate, len(feedback), len(untouched))


async def _untouched(
    session: AsyncSession,
    hotel: Hotel,
    active: PricingModel,
    feedback: pd.DataFrame,
) -> pd.DataFrame:
    """The nights the manager left alone: stay_date and room_type, one row each.

    Every room type and night with a snapshot within UNTOUCHED_DAYS of today
    that has no manager rate, and whose room type the model was trained on.
    """
    today = local_today(hotel.city)
    nights = await snapshot_repo.snapshotted_nights(
        session,
        hotel.id,
        start=today - timedelta(days=UNTOUCHED_DAYS),
        end=today + timedelta(days=UNTOUCHED_DAYS),
    )
    trained_on = active.training_summary.get("room_types", [])
    touched = set(zip(feedback["stay_date"], feedback["room_type"], strict=True))
    return pd.DataFrame(
        [
            {"stay_date": n["stay_date"], "room_type": n["room_type"]}
            for n in nights
            if (n["stay_date"], n["room_type"]) not in touched
            and (not trained_on or n["room_type"] in trained_on)
        ],
        columns=pd.Index(["stay_date", "room_type"]),
    )


async def _model(session: AsyncSession, model_id: int) -> PricingModel:
    model = await model_repo.get_pricing_model(session, model_id)
    if model is None:
        raise NotFoundError("Pricing model", model_id)
    return model


async def _features(
    session: AsyncSession, hotel: Hotel, feedback: pd.DataFrame
) -> pd.DataFrame:
    """The model's inputs for each night the manager priced, row for row.

    Built as recommendations build them, so past and future nights both work.
    """
    days = sorted(set(feedback["stay_date"]))
    events = await events_for(session, hotel.city, days)
    x = build_features(
        feedback[["stay_date", "room_type"]],
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
    )
    return x[FEATURES]
