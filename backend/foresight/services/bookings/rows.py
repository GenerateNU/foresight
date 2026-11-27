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
    """Lists what each booked room paid for each night it stayed.

    A booking covers one room for a whole stay; this splits it into one row
    per night, so the model sees each night a room was sold, when it was
    booked, and at what price. Only bookings of the one room code and rate
    plan the model prices count. A stay crossing either edge of the window
    contributes only its nights inside it. Free or unpriced rooms are left
    out.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        room_type_code (str): The room code priced.
        rate_plan (str): The rate plan priced.

    Returns:
        pd.DataFrame: Sorted by stay_date, with columns `stay_date`;
            `booked_on`, the day it was booked (one dated after its night,
            like a late entry, is kept and counts as 0 days ahead); and
            `rate`, the nett rate per night before VAT (every night of a stay
            gets the stay's average, so a weekend night in a longer stay is
            blurred with its weekdays). Empty without bookings.
    """
    bookings = await booking_repo.list_bookings(
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
    """Lists a stay's nights inside a window.

    Args:
        stay (Booking): The booking.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Yields:
        date: Each night.
    """
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
