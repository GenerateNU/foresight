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
import pandas as pd

from foresight.repository import booking as booking_repo
from foresight.repository import feedback as feedback_repo
from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.services.domain.booking import BOOKING_ROW_COLUMNS, booking_rows
from foresight.services.domain.city import local_date
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import events_for, hotel_location
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel, TunedEBMModel
from foresight.services.ml.features import FEATURES, build_features
from foresight.services.ml.resources import measure
from foresight.services.ml.weighting import combine_identical_rows

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel, RoomType
    from foresight.database.models.pricing_model import PricingModel

ALGORITHM = "ebm"
# The one product the model prices (decision 0079): Guestline's DOUBLE room,
# room only. Half of Beresford's room-nights are DOUBLE, and breakfast adds
# about €27 a night, so mixing room types and plans blurs the price. Training
# reads only these bookings; the room type is named after the code.
MAIN_ROOM_CODE = "DOUBLE"
MAIN_RATE_PLAN = "BAR_RO"
# Fewest booked rooms to train on (decision 0076); EBM holds some back for its
# own early stopping.
MIN_TRAINING_ROWS = 120
# What every version learns to predict, stored in its metrics as `target`: each
# booked room's rate per night before VAT (decisions 0056, 0076).
TARGET = "adr_nett"
# A manager rate is a booked-room row of its own weighing this share of the
# night's booked rooms, and at least 1, so one rate isn't drowned out by the
# night's sales (decision 0076).
MANAGER_SHARE = 0.25
_FEEDBACK_COLUMNS = ["id", "stay_date", "rate", "given_at"]
LIBS = ("interpret-core", "scikit-learn", "numpy", "pandas", "joblib")


@dataclass(frozen=True, slots=True)
class TrainingData:
    """Booked rooms, one row per room per night, and the model's inputs for
    them, row for row (decision 0076). Oldest night first."""

    nights: pd.DataFrame  # stay_date, booked_on, rate; one per row of x
    x: pd.DataFrame  # every input in FEATURES order
    y: pd.Series  # each room's rate per night before VAT (adr_nett)
    weights: np.ndarray  # 1 per booked room; manager rows more (0076)
    one_off_dropped: int  # nights left out as one-off (decision 0070)


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
    loaded = await _main_night_range(session, hotel)
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

    # Decision 0071: the manager's current rate is a target, before or after the
    # night, the same rule the tune-up follows. No room type yet, no feedback.
    room_type = await main_room_type(session, hotel)
    feedback_rows = (
        []
        if room_type is None
        else await feedback_repo.tuning_feedback(
            session, room_type.id, start=start, end=end
        )
    )
    feedback = pd.DataFrame(feedback_rows, columns=pd.Index(_FEEDBACK_COLUMNS))
    feedback["rate"] = pd.to_numeric(feedback["rate"], errors="coerce")
    return await _with_manager_rows(session, hotel, data, feedback, began)


async def _with_manager_rows(
    session: AsyncSession,
    hotel: Hotel,
    data: TrainingData,
    feedback: pd.DataFrame,
    began: float,
) -> PreparedTraining:
    """Booked rooms plus one row per manager rate (decision 0076).

    A manager rate is the price for booking that night on the day they set it,
    so it's a row booked that day (decision 0084), next to the night's real
    sales, which stay as they are. It weighs `manager_share` of the night's
    booked rooms, and at least 1.
    """
    if feedback.empty:
        return PreparedTraining(data, 0, began)
    rows = feedback.assign(
        booked_on=[local_date(hotel.city, t) for t in feedback["given_at"]]
    )[["stay_date", "booked_on", "rate"]]
    events = await events_for(session, hotel.city, sorted(set(rows["stay_date"])))
    x_manager = build_features(
        rows,
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=rows["booked_on"],
    )[list(data.x.columns)]
    # MANAGER_SHARE of the night's booked rooms, and at least 1, so a future
    # night with no bookings yet still counts.
    rooms = data.nights.groupby("stay_date").size()
    booked = rows["stay_date"].map(rooms).fillna(0).to_numpy(float)
    weights = np.maximum(MANAGER_SHARE * booked, 1.0)

    # Every row oldest night first, like the booked rooms.
    nights = pd.concat([data.nights, rows], ignore_index=True)
    order = nights["stay_date"].argsort(kind="stable").to_numpy()
    merged = TrainingData(
        nights=nights.iloc[order].reset_index(drop=True),
        x=pd.concat([data.x, x_manager], ignore_index=True)
        .iloc[order]
        .reset_index(drop=True),
        y=pd.concat([data.y, rows["rate"]], ignore_index=True)
        .iloc[order]
        .reset_index(drop=True),
        weights=np.concatenate([data.weights, weights])[order],
        one_off_dropped=data.one_off_dropped,
    )
    return PreparedTraining(merged, len(rows), began)


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
    saved = await model_repo.create_pricing_model(
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
        activated = await model_repo.activate_pricing_model(session, saved.id)
        assert activated is not None  # saved just above, in this transaction
        saved = activated
    return TrainingResult(
        saved,
        activate,
        round(time.monotonic() - prepared.began, 1),
        len(nights),
        metrics["training_nights"],
    )


async def training_data(
    session: AsyncSession,
    hotel: Hotel,
    *,
    start: date | None,
    end: date | None,
) -> TrainingData:
    """The hotel's booked rooms on nights in [start, end] and their inputs.

    One row per booked room per night, from live bookings of the main product
    alone (decisions 0076, 0079): a night's rows are its rooms sold, so how
    full it was is already in how much it counts, and each room weighs 1. The
    one place training data is prepared, so `train` and the backtest always
    see the same inputs. Reads only; the room type may not exist yet.
    """
    loaded = await _main_night_range(session, hotel)
    if loaded is None:
        booked = pd.DataFrame(columns=pd.Index(BOOKING_ROW_COLUMNS))
    else:
        first, last = loaded
        booked = await booking_rows(
            session,
            hotel.id,
            start=max(first, start) if start else first,
            end=min(last, end) if end else last,
            room_type_code=MAIN_ROOM_CODE,
            rate_plan=MAIN_RATE_PLAN,
        )
    # Decision 0070: a night the manager marked one-off teaches nothing.
    room_type = await main_room_type(session, hotel)
    one_off = (
        []
        if room_type is None
        else await feedback_repo.one_off_nights(
            session, room_type.id, start=start, end=end
        )
    )
    marked = {r["stay_date"] for r in one_off}
    keep = ~booked["stay_date"].isin(marked)
    one_off_dropped = int(booked.loc[~keep, "stay_date"].nunique())
    booked = booked.loc[keep].reset_index(drop=True)

    days = sorted(set(booked["stay_date"]))
    events = await events_for(session, hotel.city, days)
    x = build_features(
        booked,
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=booked["booked_on"],
    )
    return TrainingData(
        nights=booked,
        x=x[FEATURES],
        y=booked["rate"].astype(float),
        weights=np.ones(len(booked)),
        one_off_dropped=one_off_dropped,
    )


async def main_room_type(session: AsyncSession, hotel: Hotel) -> RoomType | None:
    """The room type the model prices (decision 0079), or None before the
    hotel's first training run creates it."""
    return await hotel_repo.find_room_type(session, hotel.id, MAIN_ROOM_CODE)


async def _main_night_range(
    session: AsyncSession, hotel: Hotel
) -> tuple[date, date] | None:
    """The first and last night the main product's bookings cover."""
    return await booking_repo.booked_night_range(
        session, hotel.id, room_type_code=MAIN_ROOM_CODE, rate_plan=MAIN_RATE_PLAN
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
