"""Training rows: the main product's booked rooms, plus the manager's rates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from foresight.repository import booking as booking_repo
from foresight.repository import hotel as hotel_repo
from foresight.services.domain.booking import BOOKING_ROW_COLUMNS, booking_rows
from foresight.services.domain.city import local_date
from foresight.services.domain.feedback import current_feedback
from foresight.services.domain.inputs import build_inputs
from foresight.services.ml.features import FEATURES

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel, RoomType

# The one product the model prices (decision 0079): Guestline's DOUBLE room,
# room only. Half of Beresford's room-nights are DOUBLE, and breakfast adds
# about €27 a night, so mixing room types and plans blurs the price. Training
# reads only these bookings; the room type is named after the code.
MAIN_ROOM_CODE = "DOUBLE"

MAIN_RATE_PLAN = "BAR_RO"

# A manager rate is a booked-room row of its own weighing this share of the
# night's booked rooms, and at least 1, so one rate isn't drowned out by the
# night's sales (decision 0076).
MANAGER_SHARE = 0.25


@dataclass(frozen=True, slots=True)
class TrainingData:
    """Booked rooms, one row per room per night, and the model's inputs for
    them, row for row (decision 0076). Oldest night first."""

    rows: pd.DataFrame  # stay_date, booked_on, rate; one per row of x
    x: pd.DataFrame  # every input in FEATURES order
    y: pd.Series  # each room's rate per night before VAT (adr_nett)
    weights: np.ndarray  # 1 per booked room; manager rows more (0076)
    one_off_dropped: int  # nights left out as one-off (decision 0070)


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
    loaded = await main_night_range(session, hotel)
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
    room_type = await main_room_type(session, hotel)
    feedback = await current_feedback(
        session, room_type.id if room_type else None, start=start, end=end
    )
    booked, one_off_dropped = _drop_one_off(booked, feedback.one_off_nights)
    inputs = await build_inputs(session, hotel, booked, booked_on=booked["booked_on"])
    x = inputs.x
    return TrainingData(
        rows=booked,
        x=x[FEATURES],
        y=booked["rate"].astype(float),
        weights=np.ones(len(booked)),
        one_off_dropped=one_off_dropped,
    )


async def with_manager_rows(
    session: AsyncSession,
    hotel: Hotel,
    data: TrainingData,
    *,
    start: date | None,
    end: date | None,
) -> tuple[TrainingData, int]:
    """Adds one row per current manager rate to the booked rooms.

    A manager rate is the price for booking that night on the day they set it,
    so it's a row booked that day, next to the night's real sales. It weighs
    MANAGER_SHARE of the night's booked rooms, and at least 1.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel being trained.
        data (TrainingData): Its booked rooms.
        start (date | None): First night whose rate counts; None for all.
        end (date | None): Last night whose rate counts; None for all.

    Returns:
        tuple[TrainingData, int]: The rows with the manager's added, oldest
            night first, and how many manager rates were added.
    """
    room_type = await main_room_type(session, hotel)
    feedback = await current_feedback(
        session, room_type.id if room_type else None, start=start, end=end
    )
    rows = pd.DataFrame(
        [
            (f.stay_date, local_date(hotel.city, f.created_at), float(f.rate))
            for f in feedback.training_rates
        ],
        columns=pd.Index(["stay_date", "booked_on", "rate"]),
    )
    if rows.empty:
        return data, 0
    inputs = await build_inputs(session, hotel, rows, booked_on=rows["booked_on"])
    x_manager = inputs.x[list(data.x.columns)]
    # MANAGER_SHARE of the night's booked rooms, and at least 1, so a future
    # night with no bookings yet still counts.
    rooms = data.rows.groupby("stay_date").size()
    booked = rows["stay_date"].map(rooms).fillna(0).to_numpy(float)
    weights = np.maximum(MANAGER_SHARE * booked, 1.0)

    # Every row oldest night first, like the booked rooms.
    combined = pd.concat([data.rows, rows], ignore_index=True)
    order = combined["stay_date"].argsort(kind="stable").to_numpy()
    merged = TrainingData(
        rows=combined.iloc[order].reset_index(drop=True),
        x=pd.concat([data.x, x_manager], ignore_index=True)
        .iloc[order]
        .reset_index(drop=True),
        y=pd.concat([data.y, rows["rate"]], ignore_index=True)
        .iloc[order]
        .reset_index(drop=True),
        weights=np.concatenate([data.weights, weights])[order],
        one_off_dropped=data.one_off_dropped,
    )
    return merged, len(rows)


async def main_room_type(session: AsyncSession, hotel: Hotel) -> RoomType | None:
    """The room type the model prices (decision 0079), or None before the
    hotel's first training run creates it."""
    return await hotel_repo.find_room_type(session, hotel.id, MAIN_ROOM_CODE)


async def main_night_range(
    session: AsyncSession, hotel: Hotel
) -> tuple[date, date] | None:
    """The first and last night the main product's bookings cover."""
    return await booking_repo.booked_night_range(
        session, hotel.id, room_type_code=MAIN_ROOM_CODE, rate_plan=MAIN_RATE_PLAN
    )


def combine_identical_rows(
    x: pd.DataFrame, y: pd.Series, weights: np.ndarray, stay_date: pd.Series
) -> tuple[pd.DataFrame, pd.Series, np.ndarray, np.ndarray]:
    """Merges rows the model can't tell apart: the same night and inputs.

    Booked rooms for one night that were booked on the same day have identical
    inputs. One row with their weighted mean rate and summed weight gives the
    same squared-error fit as one row each, in a fraction of the time
    (decision 0056). Nights are never merged with each other.

    Args:
        x (pd.DataFrame): The model's inputs, oldest first.
        y (pd.Series): The rate of each row.
        weights (np.ndarray): Each row's sample weight.
        stay_date (pd.Series): Each row's night, aligned with x.

    Returns:
        tuple: The merged rows' inputs, rates and weights, still oldest first,
            and for each input row the position of the merged row it went into.
    """
    keys = pd.concat(
        [pd.Series(stay_date.to_numpy(), index=x.index, name="_stay_date"), x],
        axis=1,
    )
    # sort=False numbers groups in order of first appearance, so merged rows
    # keep the input's time order.
    group = (
        keys.groupby(list(keys.columns), sort=False, dropna=False, observed=True)
        .ngroup()
        .to_numpy()
    )
    w = pd.Series(np.asarray(weights, dtype=float))
    total = w.groupby(group).sum()
    rate = (pd.Series(y.to_numpy(float)) * w).groupby(group).sum() / total
    first = pd.Series(np.arange(len(x))).groupby(group).first().to_numpy()
    return (
        x.iloc[first].reset_index(drop=True),
        rate.reset_index(drop=True).rename(y.name),
        total.to_numpy(),
        group,
    )


def _drop_one_off(booked: pd.DataFrame, one_off: set[date]) -> tuple[pd.DataFrame, int]:
    """Drops the booked rooms of nights the manager tagged one-off.

    Args:
        booked (pd.DataFrame): Booked rooms, with a stay_date column.
        one_off (set[date]): The one-off nights.

    Returns:
        tuple[pd.DataFrame, int]: The rooms kept, and how many nights were
            dropped.
    """
    keep = ~booked["stay_date"].isin(one_off)
    dropped = int(booked.loc[~keep, "stay_date"].nunique())
    return booked.loc[keep].reset_index(drop=True), dropped
