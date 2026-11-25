"""Candidate feature columns for ticket #139, built as known 30 days before each night.

One place builds the columns, so the LASSO screen and the backtest start from the
same table. Moved from lasso_screen.py; the code is unchanged except that the
trend counts from TREND_START instead of the screen's start date.

Rules, as in lasso_screen.py:
- Every feature is known 30 days before its night (HORIZON).
- Blank is not zero: counts can be 0, averages stay blank.
- January 2022 is dropped from every column, lag sources included.
- Booking columns are blank before 2023, when the booking rebuild starts to match
  the hotel's rooms sold (feature_inventory.md).
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from dateutil.easter import easter
from sqlalchemy import select

from foresight.database.models.booking import Booking, BookingCancellation
from foresight.database.session import async_session_factory
from foresight.services.bookings.rows import booking_curves, rooms_on
from foresight.services.hotels.hotel import get_hotel
from foresight.services.pricing.training_data import training_data

HOTEL_ID = 1
HORIZON = 30  # days before the night that every feature is known
DATA_END = date(2025, 12, 31)
TREND_START = pd.Timestamp("2023-01-01")  # trend_years counts from here
BOOKING_FROM = pd.Timestamp("2023-01-01")  # the booking rebuild matches from here
DROPPED = (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-01-31"))


@dataclass(frozen=True)
class Candidates:
    nights: pd.DataFrame  # priced nights, January 2022 removed
    stay: pd.Series  # each night's date
    y: pd.Series  # the rate
    weights: np.ndarray  # sample weights
    model_inputs: pd.DataFrame  # every column the current model uses
    z: pd.DataFrame  # straight-line calendar terms, for the LASSO
    holiday_flag: np.ndarray  # our Irish public-holiday flag, 1.0 or 0.0
    table: pd.DataFrame  # the candidate features, one row per night
    groups: dict  # feature name -> group


async def load():
    async with async_session_factory() as session:
        hotel = await get_hotel(session, HOTEL_ID)
        data = await training_data(session, hotel, start=None, end=DATA_END)
        booked = await session.execute(
            select(
                Booking.book_ref,
                Booking.booked_at,
                Booking.arrival,
                Booking.departure,
                Booking.rate_plan,
                Booking.market_segment,
                Booking.company_code,
                Booking.agent_code,
            ).where(Booking.hotel_id == HOTEL_ID)
        )
        bookings = pd.DataFrame(booked.all(), columns=list(booked.keys()))
        cancelled = await session.execute(
            select(
                BookingCancellation.book_ref,
                BookingCancellation.booked_at,
                BookingCancellation.cancelled_at,
                BookingCancellation.arrival,
                BookingCancellation.departure,
            ).where(BookingCancellation.hotel_id == HOTEL_ID)
        )
        cancellations = pd.DataFrame(cancelled.all(), columns=list(cancelled.keys()))
        curves = await booking_curves(
            session, HOTEL_ID, start=date(2022, 1, 1), end=DATA_END
        )
    return data, bookings, cancellations, curves


# Calendar. Irish public holidays are the same list as baseline_testing.py.
# School breaks are rules, not an official calendar, so they are approximate:
#   Halloween mid-term: the Monday-Friday week starting on the last Monday of October.
#   February mid-term: the week starting on the first Monday on or after 17 February.
#   Easter: two weeks starting on the Monday before Easter Sunday.
#   Christmas: 23 December to 5 January.
# Each break counts from the Friday night before to the Saturday night after.
# Long weekend: Friday, Saturday and Sunday nights before a Monday holiday, and
#   Thursday, Friday and Saturday nights around a Friday holiday.
# Payday weekend: Friday and Saturday nights on the 25th to the 2nd.


def first_monday(year, month):
    d = date(year, month, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def last_monday(year, month):
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=d.weekday())


def irish_public_holidays(year):
    days = {
        date(year, 1, 1),
        date(year, 3, 17),
        easter(year) + timedelta(days=1),
        first_monday(year, 5),
        first_monday(year, 6),
        first_monday(year, 8),
        last_monday(year, 10),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    if year >= 2023:  # St Brigid's Day
        feb1 = date(year, 2, 1)
        days.add(feb1 if feb1.weekday() == 4 else first_monday(year, 2))
    return days


def break_nights(monday, weeks):
    friday = monday + timedelta(days=7 * (weeks - 1) + 4)
    return pd.date_range(monday - timedelta(days=3), friday + timedelta(days=1))


YEARS = range(2022, 2026)
HOLIDAYS = sorted(set().union(*(irish_public_holidays(y_) for y_ in YEARS)))
SCHOOL = {
    "school_halloween": [break_nights(last_monday(y_, 10), 1) for y_ in YEARS],
    "school_february": [
        break_nights(
            date(y_, 2, 17) + timedelta(days=(7 - date(y_, 2, 17).weekday()) % 7), 1
        )
        for y_ in YEARS
    ],
    "school_easter": [break_nights(easter(y_) - timedelta(days=6), 2) for y_ in YEARS],
}


def calendar_columns(dates):
    """The baseline terms (z) and the calendar candidates, one row per night."""
    month, dow = dates.dt.month.to_numpy(), dates.dt.dayofweek.to_numpy()
    day = dates.dt.day.to_numpy()
    # Days from each night to each holiday: 0 is the holiday night itself.
    to_holiday = (
        np.array(HOLIDAYS, dtype="datetime64[D]")[None, :]
        - dates.to_numpy().astype("datetime64[D]")[:, None]
    ).astype(int)
    is_holiday = (to_holiday == 0).any(axis=1)

    z = pd.DataFrame({"const": np.ones(len(dates))})
    for m in range(2, 13):
        z[f"month_{m}"] = (month == m).astype(float)
    for d in range(1, 7):
        z[f"dow_{d}"] = (dow == d).astype(float)
    z["holiday"] = is_holiday.astype(float)
    weekend = np.isin(dow, (4, 5))
    for m in range(2, 13):
        z[f"weekend_x_month_{m}"] = (weekend & (month == m)).astype(float)

    long_weekend = set()
    for h in HOLIDAYS:
        offsets = {0: (-3, -2, -1), 4: (-1, 0, 1)}.get(h.weekday(), ())
        long_weekend |= {pd.Timestamp(h) + pd.Timedelta(days=o) for o in offsets}

    year_fraction = dates.dt.dayofyear.to_numpy() / 365.25
    cal = pd.DataFrame(
        {
            "season_sin1": np.sin(2 * np.pi * year_fraction),
            "season_cos1": np.cos(2 * np.pi * year_fraction),
            "season_sin2": np.sin(4 * np.pi * year_fraction),
            "season_cos2": np.cos(4 * np.pi * year_fraction),
            "night_before_holiday": (to_holiday == 1).any(axis=1),
            "night_after_holiday": (to_holiday == -1).any(axis=1),
            "near_holiday_2_3_days": (
                (np.abs(to_holiday) >= 2) & (np.abs(to_holiday) <= 3)
            ).any(axis=1),
            "long_weekend": dates.isin(long_weekend).to_numpy(),
            "payday_weekend": weekend & ((day >= 25) | (day <= 2)),
            "trend_years": (dates - TREND_START).dt.days.to_numpy() / 365.25,
        }
    ).astype(float)
    for name, spans in SCHOOL.items():
        cal[name] = dates.isin(spans[0].append(spans[1:])).to_numpy().astype(float)
    cal["school_christmas"] = (
        ((month == 12) & (day >= 23)) | ((month == 1) & (day <= 5))
    ).astype(float)
    return z, cal, is_holiday.astype(float)


# Recent history, lagged so every value was known 30 days before the night:
#   rate and rooms sold on the same weekday 5, 6, 7 and 8 weeks back (mean of
#   those present, at least 2), the same night last year (364 days back), and
#   week over week: mean rooms sold on nights 31-37 days back minus nights 38-44
#   days back. Unpriced nights (Christmas, and January 2022) are blank.


def history_columns(nights_, rate, sold):
    nights_ = pd.DatetimeIndex(nights_)
    days = pd.date_range(nights_.min(), nights_.max())
    rate_d = pd.Series(rate.to_numpy(), index=nights_).reindex(days)
    sold_d = pd.Series(sold.to_numpy(dtype=float), index=nights_).reindex(days)

    def four_weeks(series):
        lags = pd.concat([series.shift(k) for k in (35, 42, 49, 56)], axis=1)
        return lags.mean(axis=1).where(lags.notna().sum(axis=1) >= 2)

    week_of = lambda lag: sold_d.shift(lag).rolling(7, min_periods=4).mean()  # noqa: E731
    out = pd.DataFrame(
        {
            "rate_4_weeks_same_weekday": four_weeks(rate_d),
            "sold_4_weeks_same_weekday": four_weeks(sold_d),
            "rate_last_year": rate_d.shift(364),
            "sold_last_year": sold_d.shift(364),
            "sold_week_over_week": week_of(31) - week_of(38),
        }
    )
    return out.reindex(nights_).reset_index(drop=True)


# Bookings and cancellations, as on the books 30 days before each night.
# Counts, lead time, length of stay, group size and cancellations use both tables
# (decision 0047): the bookings table only holds rooms that were never cancelled,
# so a count from it alone would miss every room cancelled after the cutoff.
# The mix columns (rate plan, segment, company, agent) exist only for rooms that
# were never cancelled, because the Cancellations report doesn't carry them. They
# are measured on that survivor sample and flagged as such in the results.


def room_nights(bookings, cancellations):
    """One row per room per night stayed, with when it was booked and cancelled."""
    gone = cancellations.sort_values("cancelled_at").drop_duplicates(
        "book_ref", keep="last"
    )
    live = bookings[~bookings["book_ref"].isin(gone["book_ref"])]
    rooms = pd.concat([live, gone], ignore_index=True)
    rooms["booked_on"] = pd.to_datetime(rooms["booked_at"]).dt.normalize()
    rooms["cancelled_on"] = pd.to_datetime(rooms["cancelled_at"]).dt.normalize()
    rooms["arrival"] = pd.to_datetime(rooms["arrival"])
    rooms["stay_nights"] = (
        pd.to_datetime(rooms["departure"]) - rooms["arrival"]
    ).dt.days
    reservation = rooms["book_ref"].str.split("/").str[0]
    rooms["reservation_rooms"] = reservation.map(reservation.value_counts())

    each = rooms["stay_nights"].to_numpy()
    row = np.repeat(np.arange(len(rooms)), each)
    offset = np.arange(each.sum()) - np.repeat(np.cumsum(each) - each, each)
    out = rooms.iloc[row].reset_index(drop=True)
    out["stay_date"] = rooms["arrival"].to_numpy()[row] + offset.astype(
        "timedelta64[D]"
    )
    inside = (out["stay_date"] >= "2022-01-01") & (
        out["stay_date"] <= DATA_END.isoformat()
    )
    return out[inside]


def booking_columns(rn, nights_):
    def on_books(days):
        asof = rn["stay_date"] - pd.Timedelta(days=days)
        live = rn["cancelled_on"].isna() | (rn["cancelled_on"] > asof)
        return rn[(rn["booked_on"] <= asof) & live]

    on30, on37 = on_books(HORIZON), on_books(HORIZON + 7)
    asof30 = rn["stay_date"] - pd.Timedelta(days=HORIZON)
    cancelled = rn[rn["cancelled_on"].notna() & (rn["cancelled_on"] <= asof30)]
    survivors = on30[on30["cancelled_on"].isna()]
    plan = survivors["rate_plan"]

    by_night = lambda frame: frame.groupby("stay_date")  # noqa: E731
    counts = (
        pd.DataFrame(
            {
                "rooms_on_books": by_night(on30).size(),
                "rooms_on_books_week_earlier": by_night(on37).size(),
                "group_rooms": by_night(on30[on30["reservation_rooms"] >= 5]).size(),
                "cancelled_rooms": by_night(cancelled).size(),
            }
        )
        .reindex(nights_)
        .fillna(0)
    )
    means = pd.DataFrame(
        {
            "avg_lead_on_books": by_night(
                on30.assign(v=(on30["stay_date"] - on30["booked_on"]).dt.days)
            )["v"].mean(),
            "avg_stay_length_on_books": by_night(on30)["stay_nights"].mean(),
            "cancel_lead_time": by_night(
                cancelled.assign(
                    v=(cancelled["stay_date"] - cancelled["cancelled_on"]).dt.days
                )
            )["v"].mean(),
            "advance_share": by_night(
                survivors.assign(v=plan.str.startswith("ADV", na=False))
            )["v"].mean(),
            "breakfast_share": by_night(
                survivors.assign(v=plan.str.contains(r"(?:^|_)BB(?:_|$)", na=False))
            )["v"].mean(),
            "non_leisure_share": by_night(
                survivors.assign(
                    v=survivors["market_segment"].fillna("LEISURE") != "LEISURE"
                )
            )["v"].mean(),
            "company_share": by_night(
                survivors.assign(v=survivors["company_code"].notna())
            )["v"].mean(),
            "agent_share": by_night(
                survivors.assign(v=survivors["agent_code"].notna())
            )["v"].mean(),
        }
    ).reindex(nights_)
    out = pd.concat([counts, means], axis=1)
    out["booking_pickup_7d"] = out["rooms_on_books"] - out.pop(
        "rooms_on_books_week_earlier"
    )
    total = out["cancelled_rooms"] + out["rooms_on_books"]
    out["cancellation_rate"] = (out["cancelled_rooms"] / total).where(total > 0)
    return out.drop(columns="cancelled_rooms").reset_index(drop=True), on30


async def build_candidates() -> Candidates:
    data, bookings, cancellations, curves = await load()

    # January 2022 goes from every arm, lag sources included.
    stay_all = pd.to_datetime(data.rows["stay_date"])
    keep = ~((stay_all >= DROPPED[0]) & (stay_all <= DROPPED[1])).to_numpy()
    nights = data.rows[keep].reset_index(drop=True)
    stay = pd.to_datetime(nights["stay_date"])
    y = data.y[keep].astype(float).reset_index(drop=True)
    weights = np.asarray(data.weights)[keep]
    model_inputs = data.x.loc[keep].reset_index(drop=True)

    z, calendar_all, holiday_flag = calendar_columns(stay)
    history_all = history_columns(stay, y, nights["rooms_sold"])
    booking_all, _ = booking_columns(
        room_nights(bookings, cancellations), pd.DatetimeIndex(stay)
    )

    # The count must equal the rebuild in services/domain/booking.py, night for night.
    rebuilt = pd.Series(
        {
            pd.Timestamp(n): rooms_on(c, n - timedelta(days=HORIZON))
            for n, c in curves.items()
        }
    ).reindex(pd.DatetimeIndex(stay), fill_value=0)
    differs = (booking_all["rooms_on_books"].to_numpy() != rebuilt.to_numpy()).sum()
    print(f"on-books count differs from the rebuild on {differs} of {len(stay)} nights")

    # Nights before the rebuild is trustworthy are blank, not zero.
    booking_all[(stay < BOOKING_FROM).to_numpy()] = np.nan

    groups = {
        **{c: "calendar" for c in calendar_all.columns},
        **{c: "school" for c in calendar_all.columns if c.startswith("school_")},
        **{c: "recent history" for c in history_all.columns},
        **{
            c: "bookings"
            for c in [
                "rooms_on_books",
                "booking_pickup_7d",
                "group_rooms",
                "avg_lead_on_books",
                "avg_stay_length_on_books",
            ]
        },
        **{c: "cancellations" for c in ["cancellation_rate", "cancel_lead_time"]},
        **{
            c: "mix (survivors only)"
            for c in [
                "advance_share",
                "breakfast_share",
                "non_leisure_share",
                "company_share",
                "agent_share",
            ]
        },
    }
    table = pd.concat([calendar_all, history_all, booking_all], axis=1)
    assert set(groups) == set(table.columns)
    return Candidates(
        nights, stay, y, weights, model_inputs, z, holiday_flag, table, groups
    )
