"""Daily tune-up: correct the active model with the manager's rates, no full retrain.

The active model is left as it is; a small EBM learns the gap between its
predictions and the rates the manager chose (decision 0069). The correction is
saved as a new version that points to its base (decision 0078). A tune-up
always starts from the active model's base, so corrections are rebuilt each
time, never stacked.
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
from foresight.services.domain.city import local_date, local_today
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import events_for, hotel_location
from foresight.services.domain.pricing_model import LIBS
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel, TunedEBMModel
from foresight.services.ml.features import build_features

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.pricing_model import PricingModel

ALGORITHM = "ebm-tuned"
# Fewer manager rates than this and the tune-up is skipped.
MIN_TUNE_NIGHTS = 5
# Nights the manager left alone teach the correction to keep the rate they were
# shown: every past night with a snapshot this many days back (decisions 0072,
# 0074, 0078).
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

    # A tune-up always corrects a plain base, so corrections never stack: the
    # active version's own base if it is a tune-up (decision 0078).
    base_row = (
        active
        if active.base_model_id is None
        else await _model(session, active.base_model_id)
    )
    artifact = await model_repo.get_artifact(session, base_row.id)
    if artifact is None:
        raise NotFoundError("Pricing model", base_row.id)
    base = EBMModel.from_bytes(artifact)

    # The manager's nights first, then the nights they left alone. Each is
    # booked the day its price was shown, as serving priced it (decision 0076).
    both = pd.concat(
        [
            feedback[["stay_date", "room_type", "shown_at"]],
            untouched[["stay_date", "room_type", "shown_at"]],
        ],
        ignore_index=True,
    )
    x = await _features(session, hotel, both, base_row.features)

    # CPU-bound; a thread keeps the API answering meanwhile.
    model = await asyncio.to_thread(
        fit_correction,
        base,
        x.iloc[: len(feedback)],
        feedback["rate"].astype(float),
        x.iloc[len(feedback) :],
        untouched["rate"].astype(float),
    )
    correction = model.correction(x.iloc[: len(feedback)])

    saved = await model_repo.create_pricing_model(
        session,
        hotel_id=hotel.id,
        algorithm=ALGORITHM,
        description=f"Tune-up of v{base_row.version} on {len(feedback)} manager rates",
        artifact=model.to_bytes(),  # the correction only (decision 0078)
        features=list(base_row.features),
        metrics={
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
        base_model_id=base_row.id,
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


def fit_correction(
    base: EBMModel,
    x_manager: pd.DataFrame,
    y_manager: pd.Series,
    x_untouched: pd.DataFrame | None = None,
    y_untouched: pd.Series | None = None,
) -> TunedEBMModel:
    """Fits the correction on the manager's rates and the untouched nights.

    An untouched night's target is the rate the manager was shown and left
    alone (decision 0078), so a correction they accepted is kept. Pure and
    CPU-bound: `tune` and the tuning backtest both call it, so the backtest
    scores the tune-up that ships.
    """
    y = pd.Series(y_manager, dtype=float).reset_index(drop=True)
    if x_untouched is None or x_untouched.empty:
        return TunedEBMModel(base).fit(x_manager, y)
    if y_untouched is None or len(y_untouched) != len(x_untouched):
        raise ValueError("every untouched night needs the rate it was shown")
    x = pd.concat([x_manager, x_untouched], ignore_index=True)
    y = pd.concat(
        [y, pd.Series(y_untouched, dtype=float).reset_index(drop=True)],
        ignore_index=True,
    )
    return TunedEBMModel(base).fit(x, y)


async def _untouched(
    session: AsyncSession,
    hotel: Hotel,
    active: PricingModel,
    feedback: pd.DataFrame,
) -> pd.DataFrame:
    """The nights the manager left alone, one row each: stay_date, room_type,
    shown_at and rate, the rate their latest snapshot showed (decision 0078).

    Every room type and night in the UNTOUCHED_DAYS before today with a
    snapshot, no manager rate, no one-off tag (decision 0070), and a room type
    the model was trained on. Only past nights: the manager could still change
    a future one, so leaving it alone doesn't mean "no change" yet (0074).
    """
    today = local_today(hotel.city)
    start = today - timedelta(days=UNTOUCHED_DAYS)
    end = today - timedelta(days=1)
    nights = await snapshot_repo.snapshotted_nights(
        session, hotel.id, start=start, end=end
    )
    trained_on = active.training_summary.get("room_types", [])
    touched = set(zip(feedback["stay_date"], feedback["room_type"], strict=True))
    # A one-off night isn't in `feedback`, but it isn't "no change" either:
    # it teaches nothing.
    one_off = await feedback_repo.one_off_nights(
        session, hotel.id, start=start, end=end
    )
    touched |= {(row["stay_date"], row["room_type"]) for row in one_off}
    return pd.DataFrame(
        [
            {
                "stay_date": n["stay_date"],
                "room_type": n["room_type"],
                "shown_at": n["shown_at"],
                "rate": float(n["rate"]),
            }
            for n in nights
            if (n["stay_date"], n["room_type"]) not in touched
            and (not trained_on or n["room_type"] in trained_on)
        ],
        columns=pd.Index(["stay_date", "room_type", "shown_at", "rate"]),
    )


async def _model(session: AsyncSession, model_id: int) -> PricingModel:
    model = await model_repo.get_pricing_model(session, model_id)
    if model is None:
        raise NotFoundError("Pricing model", model_id)
    return model


async def _features(
    session: AsyncSession, hotel: Hotel, rows: pd.DataFrame, features: list[str]
) -> pd.DataFrame:
    """The base version's inputs for each row, built as serving builds them.

    Each row is booked on the day its price was shown (`shown_at`, in the
    hotel's timezone), so days ahead is what the manager saw; a version that
    doesn't read it simply doesn't select it (decision 0076).
    """
    days = sorted(set(rows["stay_date"]))
    events = await events_for(session, hotel.city, days)
    booked_on = pd.Series(
        [local_date(hotel.city, t) for t in rows["shown_at"]], index=rows.index
    )
    x = build_features(
        rows[["stay_date", "room_type"]],
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=booked_on,
    )
    return x[list(features)]
