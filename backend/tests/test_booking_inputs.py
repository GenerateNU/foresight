"""How booked a night was before it, as backtest inputs (decision 0049).

The input arithmetic needs no database. The rest uses the rolled-back `session`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from foresight.repository import booking as booking_repo
from foresight.repository import hotel as hotel_repo
from foresight.services.domain import backtest, pricing_model
from foresight.services.domain.model_inputs import bookings_for
from foresight.services.ml.features import (
    BACKTEST_INPUTS,
    FEATURES,
    booking_features,
)
from foresight.services.ml.weighting import MIN_WEIGHT

NIGHT = date(2025, 9, 20)
LEAD = 14
AS_OF = NIGHT - timedelta(days=LEAD)  # 6 Sep
WEEK_BEFORE = AS_OF - timedelta(days=7)  # 30 Aug


def booking(ref: str, booked_at: datetime, night: date = NIGHT) -> dict:
    return {
        "book_ref": ref,
        "booked_at": booked_at,
        "arrival": night,
        "departure": night + timedelta(days=1),
        "nights": 1,
        "room_type_code": "DOUBLE",
        "company_code": None,
        "agent_code": None,
        "adr_nett": Decimal("100.00"),
        "value_nett": Decimal("100.00"),
        "rate_plan": None,
        "market_segment": None,
    }


def cancellation(ref: str, booked_at: datetime, cancelled_at: datetime) -> dict:
    return {
        "cancel_ref": f"CN-{ref}",
        "book_ref": ref,
        "booked_at": booked_at,
        "cancelled_at": cancelled_at,
        "reason_code": None,
        "arrival": NIGHT,
        "departure": NIGHT + timedelta(days=1),
        "lost_revenue": Decimal("100.00"),
    }


async def save(session, hotel_id: int, *rows: dict) -> None:
    await booking_repo.upsert_bookings(
        session, [{**r, "hotel_id": hotel_id} for r in rows]
    )


async def sold(session, room_type_id: int, night: date, **changes) -> None:
    row = {
        "room_type_id": room_type_id,
        "stay_date": night,
        "rate": Decimal("100.00"),
        "rooms_available": 20,
        "rooms_sold": 20,
        "room_revenue": Decimal("2000.00"),
        "rooms_blocked": None,
        "rooms_out_of_service": None,
        "waitlist": None,
    }
    await hotel_repo.upsert_daily_performance(session, [{**row, **changes}])


# The inputs


def test_inputs_use_total_rooms_and_the_rooms_gained_that_week() -> None:
    nights = pd.DataFrame({"stay_date": [NIGHT], "room_type": ["Standard"]})
    bookings = pd.DataFrame(
        {"stay_date": [NIGHT], "rooms_booked": [15], "rooms_week_before": [9]}
    )

    row = booking_features(nights, bookings, total_rooms=20).iloc[0]

    assert row["pct_booked"] == 0.75
    assert row["pickup_7d"] == 6


def test_night_with_no_bookings_stored_stays_unknown() -> None:
    nights = pd.DataFrame({"stay_date": [NIGHT], "room_type": ["Standard"]})
    bookings = pd.DataFrame(columns=["stay_date", "rooms_booked", "rooms_week_before"])

    row = booking_features(nights, bookings, total_rooms=20).iloc[0]

    assert pd.isna(row["pct_booked"])
    assert pd.isna(row["pickup_7d"])


def test_inputs_line_up_with_each_room_type_row() -> None:
    nights = pd.DataFrame(
        {"stay_date": [NIGHT, NIGHT], "room_type": ["Standard", "Suite"]},
        index=[4, 7],
    )
    bookings = pd.DataFrame(
        {"stay_date": [NIGHT], "rooms_booked": [10], "rooms_week_before": [8]}
    )

    result = booking_features(nights, bookings, total_rooms=20)

    assert list(result.index) == [4, 7]
    assert list(result["pct_booked"]) == [0.5, 0.5]


# Reading the rebuild


async def bookings_row(session, hotel_id: int) -> dict:
    frame = await bookings_for(session, hotel_id, [NIGHT], lead_days=LEAD)
    return frame.iloc[0].to_dict()


async def test_counts_stop_at_the_lead_day(session, priced) -> None:
    await save(
        session,
        priced.hotel_id,
        booking("BK1/1", datetime(2025, 8, 1, 9, 0)),  # before both
        booking("BK2/1", datetime(2025, 9, 1, 9, 0)),  # in the last week
        booking("BK3/1", datetime(2025, 9, 6, 23, 59)),  # on the lead day
        booking("BK4/1", datetime(2025, 9, 7, 0, 0)),  # too late to know
    )

    row = await bookings_row(session, priced.hotel_id)

    assert row["rooms_booked"] == 3
    assert row["rooms_week_before"] == 1


async def test_cancelled_rooms_count_until_they_were_cancelled(session, priced) -> None:
    gone_early = cancellation(
        "BK1/1", datetime(2025, 8, 1, 9, 0), datetime(2025, 9, 1, 9, 0)
    )
    gone_late = cancellation(
        "BK2/1", datetime(2025, 8, 1, 9, 0), datetime(2025, 9, 10, 9, 0)
    )
    await booking_repo.upsert_cancellations(
        session,
        [{**row, "hotel_id": priced.hotel_id} for row in (gone_early, gone_late)],
    )

    row = await bookings_row(session, priced.hotel_id)

    assert row["rooms_booked"] == 1  # the late one, still on the books then
    assert row["rooms_week_before"] == 2


async def test_day_with_no_bookings_stored_is_left_out(session, priced) -> None:
    frame = await bookings_for(session, priced.hotel_id, [NIGHT], lead_days=LEAD)

    assert frame.empty


async def test_no_days_gives_an_empty_frame(session, priced) -> None:
    frame = await bookings_for(session, priced.hotel_id, [], lead_days=LEAD)

    assert frame.empty


# Training


async def loaded_hotel(session, hotel_id: int):
    return await hotel_repo.get_hotel(session, hotel_id)


async def test_training_data_has_every_input_at_the_lead_asked_for(
    session, priced
) -> None:
    await sold(session, priced.room_type_id, NIGHT)
    await save(session, priced.hotel_id, booking("BK1/1", datetime(2025, 9, 1, 9, 0)))
    hotel = await loaded_hotel(session, priced.hotel_id)

    near = await pricing_model.training_data(
        session, hotel, start=None, end=None, lead_days=7
    )
    far = await pricing_model.training_data(
        session, hotel, start=None, end=None, lead_days=30
    )

    assert list(near.x.columns) == BACKTEST_INPUTS
    assert near.x["pct_booked"].iloc[0] == 0.05  # 1 of the hotel's 20 rooms
    assert far.x["pct_booked"].iloc[0] == 0


async def test_a_sold_out_night_with_a_room_out_of_service_is_full(
    session, priced
) -> None:
    await sold(session, priced.room_type_id, NIGHT)
    await sold(
        session,
        priced.room_type_id,
        NIGHT + timedelta(days=1),
        rooms_sold=19,
        rooms_out_of_service=1,
    )
    hotel = await loaded_hotel(session, priced.hotel_id)

    data = await pricing_model.training_data(session, hotel, start=None, end=None)

    assert data.weights[0] == data.weights[1]
    assert data.weights[0] > MIN_WEIGHT


async def test_training_a_model_leaves_booking_inputs_out(
    session, priced, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = {}

    def fit(x, *_):
        seen["columns"] = list(x.columns)
        raise InterruptedError

    monkeypatch.setattr(pricing_model, "_fit", fit)
    monkeypatch.setattr(pricing_model, "MIN_TRAINING_NIGHTS", 1)
    await sold(session, priced.room_type_id, NIGHT)
    hotel = await loaded_hotel(session, priced.hotel_id)

    with pytest.raises(InterruptedError):
        await pricing_model.train(
            session,
            hotel,
            description=None,
            start=None,
            end=None,
            activate=False,
            params={},
        )

    assert seen["columns"] == FEATURES


# The backtest's nights


async def test_backtest_can_leave_out_early_nights(session, priced) -> None:
    await sold(session, priced.room_type_id, date(2024, 6, 1))
    await sold(session, priced.room_type_id, date(2025, 1, 1))
    await sold(session, priced.room_type_id, date(2025, 3, 1))
    hotel = await loaded_hotel(session, priced.hotel_id)

    split = await backtest._split(session, hotel, 30, date(2024, 12, 21), LEAD)

    assert list(split.data.nights["stay_date"]) == [
        date(2025, 1, 1),
        date(2025, 3, 1),
    ]
