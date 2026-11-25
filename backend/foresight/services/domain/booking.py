"""Bookings: what each booked room paid, one row per night, for training."""

from collections.abc import Iterator
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.booking import Booking
from foresight.repository import booking as booking_repo

BOOKING_ROW_COLUMNS = ["stay_date", "booked_on", "rate"]


async def booking_rows(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date,
    end: date,
    room_type_code: str,
    rate_plan: str,
) -> pd.DataFrame:
    """What each booked room paid for each night it stayed, for training.

    A booking covers one room for a whole stay. This splits it into one row per
    night, so the model sees each night a room was sold, when it was booked,
    and at what price (decision 0056).

    Only bookings of one room code and rate plan, the product the model
    prices (decision 0079).

    `start` and `end` are stay dates, inclusive: usually the training window.
    A stay crossing either edge contributes only its nights inside the window;
    when it was booked doesn't matter.

    Columns:
        stay_date: the night.
        booked_on: the day the booking was made. One dated after its night
            (late entries, no-shows) is kept; build_features gives it 0 days
            ahead.
        rate: the booking's nett rate per night, before VAT. Every night of a
            stay gets the stay's average, so a weekend night in a longer stay
            is blurred with its weekdays.

    Cancelled bookings are left out, and so are free or unpriced rooms. Sorted
    by stay_date. Empty if the hotel has no bookings in the window.
    """
    bookings = await booking_repo.list_live_bookings(
        session,
        hotel_id,
        start=start,
        end=end,
        room_type_code=room_type_code,
        rate_plan=rate_plan,
    )
    rows = pd.DataFrame(
        [
            (night, b.booked_at.date(), float(b.adr_nett))
            for b in bookings
            for night in _nights(b, start, end)
        ],
        columns=pd.Index(BOOKING_ROW_COLUMNS),
    )
    return (
        rows.loc[training_mask(rows["rate"])]
        .sort_values("stay_date", kind="stable")
        .reset_index(drop=True)
    )


def _nights(stay: Booking, start: date, end: date) -> Iterator[date]:
    night = max(stay.arrival, start)
    while night < stay.departure and night <= end:
        yield night
        night += timedelta(days=1)


def training_mask(rate: pd.Series) -> np.ndarray:
    """Marks which nights can be used for training.

    Free or staff rooms (rate of 0 or less) and nights with no listed rate say
    nothing about pricing, so they're left out entirely rather than weighted.

    Args:
        rate (pd.Series): Price listed each night.

    Returns:
        np.ndarray: True for each night to train on.
    """
    rate = rate.to_numpy(float)
    return ~np.isnan(rate) & (rate > 0)
