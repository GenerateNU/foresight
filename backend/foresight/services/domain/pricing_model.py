"""Pricing models: train a new version for a hotel, and read the versions.

Training only reads what's already ingested (bookings, performance and
events); it never fetches. Every run makes a new version, so earlier ones stay
to compare against. Activation follows decision 0009: a new version is saved
inactive and becomes the hotel's active one only once training succeeded,
unless the caller asks to keep the current one serving.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from foresight.repository import feedback as feedback_repo
from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.services.domain.booking import booking_rows
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import events_for, hotel_location
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.base import score
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES, LEAD, build_features
from foresight.services.ml.feedback import apply_feedback
from foresight.services.ml.resources import measure
from foresight.services.ml.weighting import (
    combine_identical_rows,
    sample_weights,
    training_mask,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.pricing_model import PricingModel

logger = logging.getLogger(__name__)

ALGORITHM = "ebm"
# EBM needs enough rows for its own validation split plus our calibration set.
# Rows are booked rooms or nights, whichever the hotel trains on (0056).
MIN_TRAINING_ROWS = 120
# What a version learned to predict, stored in its metrics as `target`
# (decision 0056): each booked room's nett rate, or the night's average rate.
TARGET_BOOKINGS = "adr_nett"
TARGET_NIGHTS = "arr"
# Share of the most recent rows scored after training; also the conformal
# calibration share (decision 0005), so metrics describe unseen nights.
HOLDOUT_FRAC = 0.15
_NIGHT_COLUMNS = [
    "stay_date",
    "room_type",
    "rate",
    "rooms_sold",
    "rooms_available",
    "rooms_out_of_service",
]
_FEEDBACK_COLUMNS = ["id", "stay_date", "room_type", "verdict", "rate"]
_LIBS = ("interpret-core", "scikit-learn", "numpy", "pandas", "joblib")


@dataclass(frozen=True, slots=True)
class TrainingData:
    """The rows a model trains on and its inputs for them, row for row.

    Rows are booked rooms, one per room per night, if the hotel can train on
    bookings; otherwise priced nights (decision 0056). Oldest first.
    """

    nights: pd.DataFrame  # stay_date, room_type, rate, ...; one row per row of x
    x: pd.DataFrame  # the inputs this version trains on, in FEATURES order
    y: pd.Series  # the rate: adr_nett for booked rooms, the night's rate otherwise
    weights: np.ndarray  # 1 per booked room; occupancy for nights (0003)
    events_fetched: set[date]  # nights an events backfill covered (0041)
    target: str  # TARGET_BOOKINGS or TARGET_NIGHTS
    reason: str | None  # why it fell back to nights; None on booked rooms

    @property
    def from_bookings(self) -> bool:
        return self.target == TARGET_BOOKINGS


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
        what = "booked rooms" if data.from_bookings else "priced nights"
        raise InvalidRequestError(
            f"{len(nights)} {what} to train on; need at least {MIN_TRAINING_ROWS}"
        )

    # Decision 0044: what the manager said after a night changes how it trains.
    feedback_rows = await feedback_repo.training_feedback(
        session, hotel.id, start=start, end=end
    )
    feedback = pd.DataFrame(feedback_rows, columns=pd.Index(_FEEDBACK_COLUMNS))
    feedback["rate"] = pd.to_numeric(feedback["rate"], errors="coerce")  # None -> NaN
    # Feedback judges a night, so it's weighed against the night's average
    # rate and carried onto each of its booked rooms as a ratio, keeping how
    # far apart they were (decision 0056). On night rows the average is the
    # night's own rate, so the ratio is the replacement itself.
    key = [nights["stay_date"], nights["room_type"]]
    night_rate = data.y.groupby(key).transform("mean")
    effect = apply_feedback(nights, feedback, night_rate, data.weights)
    return PreparedTraining(
        data=data,
        y=data.y * (effect.rate / night_rate),
        weights=effect.weights,
        used=effect.used.drop_duplicates("feedback_id"),  # not once per room
        began=began,
    )


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
    metrics["target"] = data.target
    metrics["training_rows"] = len(data.nights)
    metrics["training_nights"] = int(data.nights["stay_date"].nunique())
    metrics["feedback_nights"] = len(prepared.used)
    metrics["feedback_rates_replaced"] = int(prepared.used["rate_replaced"].sum())
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
        lib_versions={lib: version(lib) for lib in _LIBS},
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
    """The hotel's training rows in [start, end] and their model inputs.

    Rows are booked rooms, one per room per night with its days booked ahead,
    when the hotel has bookings and a single room type; otherwise priced
    nights, without lead_days (decision 0056). The one place training data is
    prepared, so `train` and the backtest always see the same inputs.
    """
    rows = await hotel_repo.list_nights(session, hotel.id, start=start, end=end)
    nights = pd.DataFrame(rows, columns=pd.Index(_NIGHT_COLUMNS))
    # Rates arrive as Decimal or None; None becomes NaN.
    rate = pd.Series(nights["rate"], dtype=float)
    nights["rate"] = rate

    # Decision 0004: free/staff/unpriced nights go before features and weights,
    # so all three line up row for row.
    nights = nights.loc[training_mask(rate)].reset_index(drop=True)

    booked, reason = await _booked_rooms(session, hotel, nights)
    if booked is None:
        logger.info("hotel %s trains on nights: %s", hotel.id, reason)
        sellable = nights["rooms_available"] - nights["rooms_out_of_service"].fillna(0)
        occupancy = nights["rooms_sold"] / sellable
        train_rows, booked_on = nights, None
        weights = sample_weights(occupancy.clip(0, 1))
        columns = [f for f in FEATURES if f != LEAD]
        target = TARGET_NIGHTS
    else:
        # Each row is a price a guest paid, so each counts once: the vacancy
        # weight (0003) judges a night's listed rate, not a sale (0056).
        train_rows, booked_on = booked, booked["booked_on"]
        weights = np.ones(len(booked))
        columns = FEATURES
        target = TARGET_BOOKINGS

    days = sorted(set(train_rows["stay_date"]))
    events = await events_for(session, hotel.city, days)
    x = build_features(
        train_rows,
        events.frame,
        events_fetched=events.fetched,
        events_impacts=events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=booked_on,
    )
    return TrainingData(
        nights=train_rows,
        x=x[columns],
        y=train_rows["rate"],
        weights=weights,
        events_fetched=events.fetched,
        target=target,
        reason=reason,
    )


async def _booked_rooms(
    session: AsyncSession, hotel: Hotel, nights: pd.DataFrame
) -> tuple[pd.DataFrame | None, str | None]:
    """Booked rooms over the priced nights' span, or None and why not.

    Bookings carry Guestline's room codes, which don't map to room types yet,
    so only a hotel with a single room type trains on them; every booking
    takes that type (decision 0056).
    """
    if nights.empty:
        return None, "no priced nights"
    room_types = await hotel_repo.list_room_types(session, hotel.id)
    if len(room_types) != 1:
        return None, (
            f"it has {len(room_types)} room types, and bookings don't map to "
            "room types yet"
        )
    booked = await booking_rows(
        session,
        hotel.id,
        start=nights["stay_date"].min(),
        end=nights["stay_date"].max(),
    )
    if booked.empty:
        return None, "it has no bookings loaded in the window"
    booked["room_type"] = room_types[0].name
    return booked, None


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
