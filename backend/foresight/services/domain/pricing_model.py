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
from foresight.services.ml.base import score
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES, build_features
from foresight.services.ml.feedback import manager_row_weights
from foresight.services.ml.resources import measure
from foresight.services.ml.weighting import combine_identical_rows

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel, RoomType
    from foresight.database.models.pricing_model import PricingModel

ALGORITHM = "ebm"
# EBM needs enough rows for its own validation split plus our calibration set.
# Rows are booked rooms (decision 0076).
MIN_TRAINING_ROWS = 120
# What every version learns to predict, stored in its metrics as `target`: each
# booked room's rate per night before VAT (decisions 0056, 0076).
TARGET = "adr_nett"
# Share of the most recent rows scored after training; also the conformal
# calibration share (decision 0005), so metrics describe unseen nights.
HOLDOUT_FRAC = 0.15
_FEEDBACK_COLUMNS = ["id", "stay_date", "room_type", "rate", "shown_at"]
LIBS = ("interpret-core", "scikit-learn", "numpy", "pandas", "joblib")


@dataclass(frozen=True, slots=True)
class TrainingData:
    """Booked rooms, one row per room per night, and the model's inputs for
    them, row for row (decision 0076). Oldest night first."""

    nights: pd.DataFrame  # stay_date, room_type, booked_on, rate; one per row of x
    x: pd.DataFrame  # every input in FEATURES order
    y: pd.Series  # each room's rate per night before VAT (adr_nett)
    weights: np.ndarray  # 1 per booked room; manager rows more (0076)
    events_fetched: set[date]  # nights an events backfill covered (0041)
    one_off_dropped: int  # nights left out as one-off (decision 0070)


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: PricingModel
    activated: bool
    seconds: float
    training_rows: int  # booked rooms or nights, whichever it trained on
    training_nights: int  # distinct nights among them
    feedback_used: int  # nights whose rate or weight the manager's feedback changed


async def check_trainable(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> Hotel:
    """Fail fast, before a job is queued, if training can't run.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: start is after end, the hotel doesn't have
            exactly one room type, or no booked nights fall in the window.
    """
    hotel = await get_hotel(session, hotel_id)
    if start is not None and end is not None and start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    await _only_room_type(session, hotel)
    loaded = await booking_repo.booked_night_range(session, hotel.id)
    if loaded is None:
        raise InvalidRequestError(
            "no bookings are loaded for this hotel; upload reservations first"
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

    data: TrainingData
    y: pd.Series  # the rate after feedback
    weights: np.ndarray  # after feedback
    used: pd.DataFrame  # feedback that changed a night, once per piece
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
    # night, the same rule the tune-up follows.
    feedback_rows = await feedback_repo.tuning_feedback(
        session, hotel.id, start=start, end=end
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

    A manager rate is the price for booking that night on the day they saw the
    recommendation, so it's a row booked that day, next to the night's real
    sales, which stay as they are. It weighs `manager_share` of the night's
    booked rooms, and at least 1.
    """
    if feedback.empty:
        used = pd.DataFrame(columns=["feedback_id", "rate_replaced", "weight_factor",
                                     "training_rate"])  # fmt: skip
        return PreparedTraining(data, data.y, data.weights, used, began)
    rows = feedback.assign(
        booked_on=[local_date(hotel.city, t) for t in feedback["shown_at"]]
    )[["stay_date", "room_type", "booked_on", "rate"]]
    events = await events_for(session, hotel.city, sorted(set(rows["stay_date"])))
    x_manager = build_features(
        rows,
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=rows["booked_on"],
    )[list(data.x.columns)]
    rooms = data.nights.groupby("stay_date").size()
    weights = manager_row_weights(rows["stay_date"], rooms)

    # Every row oldest night first, so the holdout stays the newest nights.
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
        events_fetched=data.events_fetched | events.fetched,
        one_off_dropped=data.one_off_dropped,
    )
    used = pd.DataFrame(
        {
            "feedback_id": feedback["id"].astype(int).to_numpy(),
            "rate_replaced": False,
            "weight_factor": weights,
            "training_rate": rows["rate"].to_numpy(float),
        }
    )
    return PreparedTraining(merged, merged.y, merged.weights, used, began)


async def fit(
    prepared: PreparedTraining, params: dict[str, Any]
) -> tuple[dict[str, Any], bytes]:
    """Fit and score a model on prepared rows; returns its metrics and artifact.

    Needs no database. CPU-bound for seconds to minutes, so it runs in a
    thread to keep the API answering.
    """
    data = prepared.data
    metrics, artifact = await asyncio.to_thread(
        _fit, data.x, prepared.y, prepared.weights, data.nights, params
    )
    metrics["target"] = TARGET
    metrics["training_rows"] = len(data.nights)
    metrics["training_nights"] = int(data.nights["stay_date"].nunique())
    metrics["feedback_nights"] = len(prepared.used)
    metrics["feedback_rates_replaced"] = int(prepared.used["rate_replaced"].sum())
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
    to. Does not commit."""
    nights = prepared.data.nights
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
    )
    await model_repo.link_feedback(
        session, saved.id, prepared.used.to_dict(orient="records")
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
        len(prepared.used),
    )


async def training_data(
    session: AsyncSession,
    hotel: Hotel,
    *,
    start: date | None,
    end: date | None,
) -> TrainingData:
    """The hotel's booked rooms on nights in [start, end] and their inputs.

    One row per booked room per night, from live bookings alone (decision
    0076): a night's rows are its rooms sold, so how full it was is already in
    how much it counts, and each room weighs 1. The one place training data is
    prepared, so `train` and the backtest always see the same inputs.

    Raises:
        InvalidRequestError: The hotel doesn't have exactly one room type.
    """
    room_type = await _only_room_type(session, hotel)
    loaded = await booking_repo.booked_night_range(session, hotel.id)
    if loaded is None:
        booked = pd.DataFrame(columns=pd.Index(BOOKING_ROW_COLUMNS))
    else:
        first, last = loaded
        booked = await booking_rows(
            session,
            hotel.id,
            start=max(first, start) if start else first,
            end=min(last, end) if end else last,
        )
    booked["room_type"] = room_type.name

    # Decision 0070: a night the manager marked one-off teaches nothing.
    one_off = await feedback_repo.one_off_nights(
        session, hotel.id, start=start, end=end
    )
    marked = {r["stay_date"] for r in one_off if r["room_type"] == room_type.name}
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
        events_fetched=events.fetched,
        one_off_dropped=one_off_dropped,
    )


async def _only_room_type(session: AsyncSession, hotel: Hotel) -> RoomType:
    """The hotel's one room type.

    Bookings carry Guestline's room codes, which don't map to room types yet,
    so every booking takes the hotel's single room type (decision 0056).

    Raises:
        InvalidRequestError: The hotel has none, or more than one.
    """
    room_types = await hotel_repo.list_room_types(session, hotel.id)
    if len(room_types) != 1:
        raise InvalidRequestError(
            f"training needs exactly one room type; this hotel has "
            f"{len(room_types)}, and bookings don't map to room types yet"
        )
    return room_types[0]


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
    """Fit, score on the held-out rows, and serialize. Returns the metrics,
    with the fit's time and memory, and the artifact to store.

    Rows the model can't tell apart are merged first (decision 0056), so booked
    rooms fit in a fraction of the time; scores are still per original row.
    """
    xc, yc, wc, group = combine_identical_rows(x, y, weights, nights["stay_date"])
    with measure() as cost:
        model = EBMModel(alpha=0.2, calibration_frac=HOLDOUT_FRAC, **params).fit(
            xc, yc, sample_weight=wc
        )
    cut = int(len(xc) * (1 - HOLDOUT_FRAC))
    held = group >= cut
    assert model.holdout_pred is not None
    pred = model.holdout_pred[group[held] - cut]
    metrics = _metrics(model, pred, y[held], nights.loc[held])
    return {**metrics, **cost}, model.to_bytes()


def _metrics(
    model: EBMModel, pred: np.ndarray, y: pd.Series, nights: pd.DataFrame
) -> dict[str, Any]:
    """Scores on the most recent rows; these also calibrated the interval.

    The kept model trained on these rows too, so its own scores here would
    look too good; `pred` is the first fit's, on rows it hadn't seen
    (decision 0045).
    """
    margin = model.interval_margin(model.alpha)
    scores = score(y, pred, pred - margin, pred + margin)
    return {
        **{k: (None if v is None else round(float(v), 4)) for k, v in scores.items()},
        "interval_level": 1 - model.alpha,
        "interval_margin": round(model.interval_margin(model.alpha), 2),
        "holdout_rows": len(y),
        "holdout_nights": int(nights["stay_date"].nunique()),
        "holdout_start": nights["stay_date"].min().isoformat(),
        "holdout_end": nights["stay_date"].max().isoformat(),
        "mean_rate": round(float(np.mean(y)), 2),
    }
