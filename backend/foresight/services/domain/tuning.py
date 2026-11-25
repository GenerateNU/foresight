"""Daily tune-up: correct the active model with the manager's rates, no full retrain.

The active model is left as it is; a small EBM learns the gap between its
predictions and the rates the manager chose. The correction is saved as a new
version that points to its base. A tune-up always starts from the active
model's base, so corrections are rebuilt each time, never stacked.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.hotel import Hotel
from foresight.database.models.model import PricingModel
from foresight.repository import model as model_repo
from foresight.repository import recommendation as recommendation_repo
from foresight.services.domain.city import local_date, local_today
from foresight.services.domain.feedback import CurrentFeedback, current_feedback
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.inputs import build_inputs
from foresight.services.domain.model import (
    create_version,
    get_model,
    load_model,
)
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.ebm import EBMModel, TunedEBMModel

ALGORITHM = "ebm-tuned"
MIN_TUNE_NIGHTS = 5
UNTOUCHED_DAYS = 30


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Results                          │
#          ╰──────────────────────────────────────────────────────────╯


@dataclass(frozen=True, slots=True)
class TuneResult:
    """What a tune-up did.

    Attributes:
        version (PricingModel | None): The saved tune-up; None when skipped.
        activated (bool): Whether it started serving.
        nights_used (int): Manager rates the correction learned from.
        untouched_used (int): Nights left alone, learned as "keep this price".
        skipped (str | None): Why nothing was saved, when it wasn't.
    """

    version: PricingModel | None
    activated: bool
    nights_used: int
    untouched_used: int = 0
    skipped: str | None = None


@dataclass(frozen=True, slots=True)
class _Rows:
    """The rows a correction learns from, manager rates first.

    Attributes:
        dates (pd.Series): Each row's night.
        seen_on (pd.Series): The day each price was seen: the manager's rate
            on the day they set it, an untouched night on the day its latest
            snapshot was shown.
        rates (pd.Series): The rate each row should get.
        manager_count (int): How many of the rows are manager rates.
    """

    dates: pd.Series
    seen_on: pd.Series
    rates: pd.Series
    manager_count: int


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Tune-up                          │
#          ╰──────────────────────────────────────────────────────────╯


async def check_tunable(session: AsyncSession, hotel_id: int) -> Hotel:
    """Checks, before a job is queued, that the hotel has a model to tune.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        Hotel: The hotel, with its city loaded.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: The hotel has no active model.
    """
    hotel = await get_hotel(session, hotel_id)
    await _active_version(session, hotel)
    return hotel


async def tune(session: AsyncSession, hotel: Hotel, *, activate: bool) -> TuneResult:
    """Corrects the active model with the manager's current rates.

    Skips, saving nothing, if there are fewer than MIN_TUNE_NIGHTS rates. Does
    not commit.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel, with its city loaded.
        activate (bool): Whether the tune-up starts serving.

    Returns:
        TuneResult: The saved tune-up, or why it was skipped.

    Raises:
        InvalidRequestError: The hotel has no active model, or it predates the
            main room type.
    """
    active = await _active_version(session, hotel)
    feedback = await current_feedback(session, active.room_type_id)
    manager = feedback.training_rates
    if len(manager) < MIN_TUNE_NIGHTS:
        return TuneResult(
            None,
            False,
            len(manager),
            skipped=f"{len(manager)} manager rates; need at least {MIN_TUNE_NIGHTS}",
        )
    base_version = await _base_version(session, active)
    base = await load_model(session, base_version)
    rows = await _rows(session, hotel, active.room_type_id, feedback)
    x = (
        await build_inputs(
            session,
            hotel,
            pd.DataFrame({"stay_date": rows.dates}),
            booked_on=rows.seen_on,
        )
    ).x[list(base_version.features)]
    model = await asyncio.to_thread(fit_correction, base, x, rows.rates)
    version_row = await _save(session, hotel, base_version, model, x, rows, activate)
    return TuneResult(
        version_row, activate, rows.manager_count, len(rows.dates) - rows.manager_count
    )


def fit_correction(base: EBMModel, x: pd.DataFrame, rates: pd.Series) -> TunedEBMModel:
    """Fits a correction to the base on the rows given.

    CPU-bound, so `tune` runs it in a thread.

    Args:
        base (EBMModel): The trained base model.
        x (pd.DataFrame): The base's inputs for each row.
        rates (pd.Series): The rate each row should get, aligned with `x`.

    Returns:
        TunedEBMModel: The base with its correction trained.
    """
    return TunedEBMModel(base).fit(x, rates.astype(float).reset_index(drop=True))


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Helpers                          │
#          ╰──────────────────────────────────────────────────────────╯


async def _active_version(session: AsyncSession, hotel: Hotel) -> PricingModel:
    """Gets the active version, which must price the main room type.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.

    Returns:
        PricingModel: The active version.

    Raises:
        InvalidRequestError: The hotel has no active model, or it predates the
            main room type.
    """
    active = await model_repo.get_active_model(session, hotel.id)
    if active is None:
        raise InvalidRequestError("the hotel has no active model; train one first")
    if active.room_type_id is None:
        raise InvalidRequestError(
            "the active model predates the main room type; train a new version"
        )
    return active


async def _base_version(session: AsyncSession, active: PricingModel) -> PricingModel:
    """Gets the plain version a tune-up corrects: the active one, or its base.

    Args:
        session (AsyncSession): The database session.
        active (PricingModel): The active version.

    Returns:
        PricingModel: The base version.
    """
    if active.base_model_id is None:
        return active
    return await get_model(session, active.base_model_id)


async def _rows(
    session: AsyncSession, hotel: Hotel, room_type_id: int, feedback: CurrentFeedback
) -> _Rows:
    """Gathers the manager's rates and the nights they left alone.

    A night left alone is a past night in the UNTOUCHED_DAYS before today with
    a snapshot, no manager rate and no one-off tag. Its rate is the one its
    latest snapshot showed, so the correction keeps what the manager accepted.
    A future night doesn't count: the manager may still change it.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel, with its city loaded.
        room_type_id (int): The room type priced.
        feedback (CurrentFeedback): The current feedback for that room type.

    Returns:
        _Rows: The rows, manager rates first.
    """
    manager = feedback.training_rates
    today = local_today(hotel.city)
    shown = await recommendation_repo.snapshotted_nights(
        session,
        room_type_id,
        start=today - timedelta(days=UNTOUCHED_DAYS),
        end=today - timedelta(days=1),
    )
    touched = {f.stay_date for f in feedback.rows if f.rate is not None}
    touched |= feedback.one_off_nights
    untouched = [n for n in shown if n["stay_date"] not in touched]
    return _Rows(
        dates=pd.Series(
            [f.stay_date for f in manager] + [n["stay_date"] for n in untouched]
        ),
        seen_on=pd.Series(
            [local_date(hotel.city, f.created_at) for f in manager]
            + [local_date(hotel.city, n["shown_at"]) for n in untouched]
        ),
        rates=pd.Series(
            [float(f.rate) for f in manager] + [float(n["rate"]) for n in untouched]
        ),
        manager_count=len(manager),
    )


async def _save(
    session: AsyncSession,
    hotel: Hotel,
    base_version: PricingModel,
    model: TunedEBMModel,
    x: pd.DataFrame,
    rows: _Rows,
    activate: bool,
) -> PricingModel:
    """Saves the correction as a new version that points to its base.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        base_version (PricingModel): The version corrected.
        model (TunedEBMModel): The fitted tune-up.
        x (pd.DataFrame): Its inputs, manager rates first.
        rows (_Rows): The rows it learned from.
        activate (bool): Whether it starts serving.

    Returns:
        PricingModel: The saved version.
    """
    manager_dates = rows.dates.iloc[: rows.manager_count]
    correction = model.correction(x.iloc[: rows.manager_count])
    assert base_version.room_type_id is not None
    return await create_version(
        session,
        hotel_id=hotel.id,
        algorithm=ALGORITHM,
        description=(
            f"Tune-up of v{base_version.version} on {rows.manager_count} manager rates"
        ),
        artifact=model.to_bytes(),
        features=list(base_version.features),
        metrics={
            "tune_nights": rows.manager_count,
            "untouched_nights": len(rows.dates) - rows.manager_count,
            "mean_correction": round(float(correction.mean()), 2),
        },
        data_start=min(base_version.data_start, manager_dates.min()),
        data_end=max(base_version.data_end, manager_dates.max()),
        room_type_id=base_version.room_type_id,
        activate=activate,
        base_model_id=base_version.id,
    )
