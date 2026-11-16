"""LASSO screening for ticket #139: which candidate features explain the rate the
calendar can't, and do the survivors help the EBM on 2025?"""

# %% [markdown]
# Rules, fixed before running anything.
#
# Sample. Priced nights of hotel 1, 2023-01-01 to 2024-12-31: the screen. 2025 is
#   never seen by the screen; it only confirms the survivors. 2022 is out of the
#   screen because the booking rebuild only matches rooms sold from January 2023
#   (feature_inventory.md). January 2022 is dropped from everything, lag sources
#   included, and also from the baseline it is compared with.
# Features. Each is known 30 days before its night. Blank is not zero: counts can
#   be 0, averages stay blank. For LASSO only, blanks get the training median plus
#   a "was missing" flag; the EBM keeps blanks.
# Calendar first. The LASSO fits the rate left over after month, weekday, the
#   holiday flag and weekend-by-month (the nearest linear match to the EBM
#   baseline). Those terms are never penalised, so a feature only gets weight for
#   what the calendar doesn't explain.
# Before the LASSO. A calendar flag needs at least 10 nights off its usual value.
#   Any other feature is dropped if one value covers more than 95% of nights.
# Choosing the penalty. 12 expanding folds (test each month of 2024, train on
#   every screen night before it), scored on MAE. The penalty is the largest one
#   within one standard error of the best.
# Shortlist. A feature is kept if its weight is non-zero in the fit on the whole
#   screen and in at least 9 of the 12 fold fits, with the same sign every time.
# Confirmation. EBM, baseline plus the feature (each alone, then all together),
#   year test (train before 2025, test 2025) and the 12 rolling months of 2025.
#   A feature stays if it lowers the average monthly error by more than its
#   standard error, is better in at least 7 of 12 months, and does not raise the
#   year-test error.

# %%
from datetime import date, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dateutil.easter import easter
from joblib import Parallel, delayed
from sklearn.linear_model import lasso_path
from sqlalchemy import select

from foresight.database.models.booking import Booking, BookingCancellation
from foresight.database.session import async_session_factory
from foresight.services.domain.backtest import ALPHA
from foresight.services.domain.booking import booking_curves, rooms_on
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.pricing_model import HOLDOUT_FRAC, training_data
from foresight.services.ml.base import score
from foresight.services.ml.ebm import EBMModel

HOTEL_ID = 1
HORIZON = 30  # days before the night that every feature is known
DATA_END = date(2025, 12, 31)
SCREEN_START, SCREEN_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")
BOOKING_FROM = SCREEN_START  # the rebuild matches rooms sold from here
DROPPED = (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-01-31"))
MIN_FLAGGED_NIGHTS = 10
MAX_TOP_VALUE_SHARE = 0.95
MIN_FOLDS = 9  # of 12


# %%
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


data, bookings, cancellations, curves = await load()  # noqa: F704

# January 2022 goes from every arm, lag sources included.
stay_all = pd.to_datetime(data.nights["stay_date"])
keep = ~((stay_all >= DROPPED[0]) & (stay_all <= DROPPED[1])).to_numpy()
nights = data.nights[keep].reset_index(drop=True)
stay = pd.to_datetime(nights["stay_date"])
y = data.y[keep].astype(float).reset_index(drop=True)
weights = np.asarray(data.weights)[keep]
x_base = data.x.loc[keep, ["room_type", "day_of_week", "month"]].reset_index(drop=True)
print(f"{len(nights)} priced nights, {stay.min().date()} to {stay.max().date()}")
print(f"{len(bookings)} bookings, {len(cancellations)} cancellations")


# %% [markdown]
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


# %%
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
            "trend_years": (dates - SCREEN_START).dt.days.to_numpy() / 365.25,
        }
    ).astype(float)
    for name, spans in SCHOOL.items():
        cal[name] = dates.isin(spans[0].append(spans[1:])).to_numpy().astype(float)
    cal["school_christmas"] = (
        ((month == 12) & (day >= 23)) | ((month == 1) & (day <= 5))
    ).astype(float)
    return z, cal, is_holiday.astype(float)


z_all, calendar_all, holiday_flag = calendar_columns(stay)
print(f"{int(holiday_flag.sum())} holiday nights")


# %% [markdown]
# Recent history, lagged so every value was known 30 days before the night:
#   rate and rooms sold on the same weekday 5, 6, 7 and 8 weeks back (mean of
#   those present, at least 2), the same night last year (364 days back), and
#   week over week: mean rooms sold on nights 31-37 days back minus nights 38-44
#   days back. Unpriced nights (Christmas, and January 2022) are blank.


# %%
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


history_all = history_columns(stay, y, nights["rooms_sold"])


# %% [markdown]
# Bookings and cancellations, as on the books 30 days before each night.
# Counts, lead time, length of stay, group size and cancellations use both tables
# (decision 0047): the bookings table only holds rooms that were never cancelled,
# so a count from it alone would miss every room cancelled after the cutoff.
# The mix columns (rate plan, segment, company, agent) exist only for rooms that
# were never cancelled, because the Cancellations report doesn't carry them. They
# are measured on that survivor sample and flagged as such in the results.


# %%
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


room_nights_all = room_nights(bookings, cancellations)
booking_all, on_books_30 = booking_columns(room_nights_all, pd.DatetimeIndex(stay))

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

GROUPS = {
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
candidates = pd.concat([calendar_all, history_all, booking_all], axis=1)
assert set(GROUPS) == set(candidates.columns)
print(f"{candidates.shape[1]} candidate features")


# %%
# Screen sample and the checks that drop a feature before the LASSO.
in_screen = ((stay >= SCREEN_START) & (stay <= SCREEN_END)).to_numpy()
screen = candidates[in_screen]

rows = []
for name in candidates:
    values = screen[name].dropna().round(6)
    top = values.value_counts(normalize=True)
    flag_like = GROUPS[name] in ("calendar", "school") and values.nunique() <= 2
    off_mode = int(round((1 - top.iloc[0]) * len(values)))
    drop = (
        off_mode < MIN_FLAGGED_NIGHTS
        if flag_like
        else top.iloc[0] > MAX_TOP_VALUE_SHARE
    )
    rows.append(
        {
            "feature": name,
            "group": GROUPS[name],
            "blank %": round(100 * screen[name].isna().mean(), 1),
            "top value %": round(100 * top.iloc[0], 1),
            "nights off the usual value": off_mode,
            "dropped": drop,
        }
    )
checks = pd.DataFrame(rows).set_index("feature")
print(checks.to_string())
SCREENED = [c for c in candidates if not checks.loc[c, "dropped"]]
print(f"\nDropped before the LASSO: {[c for c in candidates if c not in SCREENED]}")
BLANKS = [c for c in SCREENED if screen[c].isna().any()]
print(f"{len(SCREENED)} features go to the LASSO; blanks flagged on {BLANKS}")


# %%
def prepare(train, test):
    """Fills blanks with the training median and adds a was-missing flag per
    column that has blanks anywhere in the screen."""
    median = train.median().fillna(0.0)
    both = []
    for frame in (train, test):
        flags = frame[BLANKS].isna().astype(float).add_suffix("_missing")
        both.append(pd.concat([frame.fillna(median), flags], axis=1))
    return both


def fit_path(z, x, target, w, alphas):
    """LASSO path for the rate left over after the calendar.

    z (the calendar terms) is never penalised: it is projected out of the rate
    and out of every feature, which gives the same fit as leaving it
    unpenalised. Weighted by sqrt(w), so each night counts as in the EBM.
    """
    root = np.sqrt(w / w.mean())[:, None]
    zr, joined = z * root, np.column_stack([target, x]) * root
    onto_z = np.linalg.lstsq(zr, joined, rcond=None)[0]
    left = joined - zr @ onto_z
    rate_left, x_left = left[:, 0], left[:, 1:]
    scale = np.sqrt((x_left**2).mean(axis=0))
    scale[scale < 1e-9] = np.inf  # a constant column can't get weight
    standard = lasso_path(x_left / scale, rate_left, alphas=alphas)[1]
    raw = standard / scale[:, None]  # euros per unit of the feature
    gamma = onto_z[:, [0]] - onto_z[:, 1:] @ raw  # the calendar terms, per penalty
    return {
        "standard": standard,
        "raw": raw,
        "gamma": gamma,
        "x_left": x_left,
        "rate_left": rate_left,
        "scale": scale,
    }


def predict(fit, z, x):
    return z @ fit["gamma"] + x @ fit["raw"]  # one column per penalty


# %%
# Penalty grid: from the weakest penalty that zeroes every weight on the screen
# down to 1/1000 of it.
screen_pos = np.flatnonzero(in_screen)
z_s = z_all.to_numpy()[screen_pos]
y_s = y.to_numpy()[screen_pos]
w_s = weights[screen_pos]
x_screen, _ = prepare(
    candidates.loc[screen_pos, SCREENED], candidates.loc[screen_pos, SCREENED]
)

sqrt_w = np.sqrt(w_s / w_s.mean())[:, None]
joined = np.column_stack([y_s, x_screen.to_numpy()]) * sqrt_w
left = joined - (z_s * sqrt_w) @ np.linalg.lstsq(z_s * sqrt_w, joined, rcond=None)[0]
sd = np.sqrt((left[:, 1:] ** 2).mean(axis=0))
alpha_max = np.max(
    np.abs((left[:, 1:] / np.where(sd < 1e-9, np.inf, sd)).T @ left[:, 0])
) / len(y_s)
alphas = alpha_max * np.logspace(0, -3, 60)

# Expanding folds: test each month of 2024, train on every screen night before it.
stay_s = stay.to_numpy()[screen_pos]
months = pd.date_range("2024-01-01", "2024-12-01", freq="MS")
cv_mae, fold_fits = [], []
for start in months:
    end = start + pd.offsets.MonthBegin(1)
    tr, te = (
        stay_s < start.to_datetime64(),
        (stay_s >= start.to_datetime64()) & (stay_s < end.to_datetime64()),
    )
    train_x, test_x = prepare(
        candidates.loc[screen_pos[tr], SCREENED],
        candidates.loc[screen_pos[te], SCREENED],
    )
    fit = fit_path(z_s[tr], train_x.to_numpy(), y_s[tr], w_s[tr], alphas)
    predicted = predict(fit, z_s[te], test_x.to_numpy())
    cv_mae.append(np.abs(predicted - y_s[te][:, None]).mean(axis=0))
    fold_fits.append(fit["standard"])
cv_mae = np.array(cv_mae)  # folds x penalties

mean_mae = cv_mae.mean(axis=0)
best = int(mean_mae.argmin())
std_error = cv_mae[:, best].std(ddof=1) / np.sqrt(len(months))
chosen = int(np.argmax(mean_mae <= mean_mae[best] + std_error))  # largest penalty
print(f"Calendar only (no feature has weight): MAE {mean_mae[0]:.2f}")
print(
    f"Best penalty: MAE {mean_mae[best]:.2f}, 1-SE penalty: MAE {mean_mae[chosen]:.2f}"
)

# Final fit on the whole screen.
full = fit_path(z_s, x_screen.to_numpy(), y_s, w_s, alphas)
names = list(x_screen.columns)
curve = pd.DataFrame(
    {
        "penalty (x the max)": alphas / alpha_max,
        "features with weight": (full["standard"] != 0).sum(axis=0),
        "CV MAE": mean_mae,
        "fold spread": cv_mae.std(axis=0, ddof=1),
    }
)
print(f"\nPenalty path (every 6th of {len(alphas)}); 1-SE pick is row {chosen}:")
print(curve.iloc[::6].round(3).to_string(index=False))


# %%
folds_on = np.array([f[:, chosen] != 0 for f in fold_fits])  # folds x features
folds_sign = np.array([np.sign(f[:, chosen]) for f in fold_fits])
weight = full["standard"][:, chosen]


# Correlation with the rate itself, and with the rate left after the calendar.
def corr(a, b):
    return np.array([np.corrcoef(a[:, j], b)[0, 1] for j in range(a.shape[1])])


with np.errstate(invalid="ignore", divide="ignore"):
    raw_corr = corr(x_screen.to_numpy(), y_s)
    partial_corr = corr(full["x_left"], full["rate_left"])
    between = np.nan_to_num(np.corrcoef(full["x_left"], rowvar=False))
np.fill_diagonal(between, 0)


def nearest_twin(j):
    """The feature most correlated with feature j, if the correlation is over 0.8."""
    other = int(np.argmax(np.abs(between[j])))
    if abs(between[j, other]) <= 0.8:
        return ""
    return f"{names[other]} ({between[j, other]:+.2f})"


twin = [nearest_twin(j) for j in range(len(names))]

table = pd.DataFrame(
    {
        "group": [GROUPS.get(n, "was-missing flag") for n in names],
        "enters at": [
            alphas[np.flatnonzero(row)[0]] / alpha_max if row.any() else 0.0
            for row in full["standard"]
        ],
        "weight (€ per SD)": weight,
        "folds picked": folds_on.sum(axis=0),
        "same sign": [
            set(folds_sign[folds_on[:, j], j]) <= {np.sign(weight[j])}
            for j in range(len(names))
        ],
        "corr with rate": raw_corr,
        "corr after calendar": partial_corr,
        "near-duplicate of": twin,
    },
    index=names,
)
table["shortlist"] = (
    (table["weight (€ per SD)"] != 0)
    & (table["folds picked"] >= MIN_FOLDS)
    & table["same sign"]
    & ~table.index.str.endswith("_missing")
)
# "enters at" is the share of the strongest penalty at which a feature first gets
# weight: the higher, the longer it survives. It doesn't depend on the penalty pick.
table = table.sort_values(
    ["enters at", "weight (€ per SD)"], ascending=False, key=lambda c: c.abs()
)
print(table.round(3).to_string())
SHORTLIST = list(table.index[table["shortlist"]])
print(f"\nShortlist ({len(SHORTLIST)}): {SHORTLIST}")
at_best = [n for n, b in zip(names, full["standard"][:, best], strict=True) if b != 0]
print(f"Non-zero at the best penalty ({len(at_best)}): {at_best}")


# %%
BLUE, ORANGE = "#2a78d6", "#eb6834"  # validated colors, colorblind-safe pair
SURFACE, GRID = "#fcfcfb", "#e5e4e0"

shown = table[table["weight (€ per SD)"] != 0].sort_values("weight (€ per SD)")
if len(shown):
    fig, ax = plt.subplots(figsize=(9, 0.4 * len(shown) + 1.6), facecolor=SURFACE)
    values = shown["weight (€ per SD)"]
    ax.barh(
        shown.index,
        values,
        height=0.6,
        color=[BLUE if v > 0 else ORANGE for v in values],
    )
    for position, (_, row) in enumerate(shown.iterrows()):
        label = f"{int(row['folds picked'])}/12"
        ax.text(
            0,
            position,
            f" {label} " if row["weight (€ per SD)"] < 0 else f" {label}",
            ha="left" if row["weight (€ per SD)"] > 0 else "right",
            va="center",
            fontsize=8,
            color="#52514e",
        )
    ax.axvline(0, color="#52514e", linewidth=1)
    ax.set_xlabel("€ per one standard deviation, on top of the calendar")
    ax.set_title("What the LASSO keeps (label: folds that also picked it)")
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.show()


# %% [markdown]
# Confirmation on 2025. Candidate columns go to the EBM as they are (blanks kept).
# Every arm trains on the same nights as the baseline: January 2022 is out of all
# of them. The baseline is calendar plus the Irish public-holiday flag.


# %%
x_all = x_base.assign(is_public_holiday=holiday_flag).join(candidates)
BASELINE = ["room_type", "day_of_week", "month", "is_public_holiday"]
ARMS = {"baseline": []}
ARMS.update({f"+ {name}": [name] for name in SHORTLIST})
if len(SHORTLIST) > 1:
    ARMS["+ all of the shortlist"] = SHORTLIST

FOLDS = {"year 2025": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01"))}
for month_start in pd.date_range("2025-01-01", "2025-12-01", freq="MS"):
    FOLDS[month_start.strftime("%Y-%m")] = (
        month_start,
        month_start + pd.offsets.MonthBegin(1),
    )


def run_fold(arm, start, end):
    columns = BASELINE + ARMS[arm]
    train = (stay < start).to_numpy()
    test = ((stay >= start) & (stay < end)).to_numpy()
    model = EBMModel(alpha=ALPHA, calibration_frac=HOLDOUT_FRAC)
    model.fit(
        x_all.loc[train, columns],
        y[train].reset_index(drop=True),
        sample_weight=weights[train],
    )
    predicted, low, high = model.predict_interval(x_all.loc[test, columns])
    return {
        "arm": arm,
        "fold": "",
        **score(y[test].to_numpy(), predicted, low, high),
    }


def run_all():
    jobs = [(arm, fold, s, e) for arm in ARMS for fold, (s, e) in FOLDS.items()]
    done = Parallel(n_jobs=-1)(delayed(run_fold)(arm, s, e) for arm, _, s, e in jobs)
    for result, (_, fold, _, _) in zip(done, jobs, strict=True):
        result["fold"] = fold
    return pd.DataFrame(done)


results = run_all() if SHORTLIST else pd.DataFrame()


# %%
def summarize(results):
    year = results[results["fold"] == "year 2025"].set_index("arm")
    rolling = results[results["fold"] != "year 2025"]
    base = rolling[rolling["arm"] == "baseline"].set_index("fold")["mae"]
    rows = []
    for arm, runs in rolling.groupby("arm", sort=False):
        diff = runs.set_index("fold")["mae"] - base  # positive = worse than baseline
        std_error = diff.std() / np.sqrt(len(diff)) if arm != "baseline" else 0.0
        rows.append(
            {
                "arm": arm,
                "year MAE": year.loc[arm, "mae"],
                "year bias": year.loc[arm, "bias"],
                "2025 rolling MAE": runs["mae"].mean(),
                "vs baseline": diff.mean(),
                "std error": std_error,
                "months better": int((diff < 0).sum()),
            }
        )
    out = pd.DataFrame(rows).set_index("arm")
    out["keep"] = (
        (out["vs baseline"] <= -out["std error"])
        & (out["months better"] >= 7)
        & (out["year MAE"] <= out.loc["baseline", "year MAE"])
    )
    out.loc["baseline", "keep"] = False
    return out


if len(results):
    confirmation = summarize(results)
    print(confirmation.round(2).to_string())
else:
    print("Nothing on the shortlist, so nothing to confirm.")


# %%
def monthly_differences(results):
    """MAE in each month of 2025 minus the baseline's (negative = better)."""
    rolling = results[results["fold"] != "year 2025"]
    mae = rolling.pivot(index="fold", columns="arm", values="mae")
    return mae.sub(mae["baseline"], axis=0).drop(columns="baseline")


if len(results):
    monthly = monthly_differences(results)
    print((monthly.T).round(1).to_string())

    everything = (
        "+ all of the shortlist" if "+ all of the shortlist" in monthly else None
    )
    arms = confirmation.drop(index="baseline")
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(10, 3 + 0.45 * len(arms)), facecolor=SURFACE
    )
    if everything:
        gap = monthly[everything]
        top.bar(
            range(len(gap)),
            gap.values,
            color=[BLUE if g < 0 else ORANGE for g in gap.values],
        )
        top.set_xticks(range(len(gap)))
        top.set_xticklabels([m[5:] for m in gap.index])
        top.set_title("All shortlisted features: error vs baseline, each month of 2025")
        top.set_ylabel("€ (below 0 = better)")
        top.axhline(0, color="#52514e", linewidth=1)
    arms = arms.sort_values("vs baseline", ascending=False)
    bottom.barh(
        arms.index,
        arms["vs baseline"],
        xerr=arms["std error"],
        color=[BLUE if v < 0 else ORANGE for v in arms["vs baseline"]],
        ecolor="#52514e",
        height=0.6,
    )
    bottom.axvline(0, color="#52514e", linewidth=1)
    bottom.set_title("Average monthly change vs baseline (bars: one standard error)")
    bottom.set_xlabel("€ per month (below 0 = better)")
    for ax in (top, bottom):
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y" if ax is top else "x", color=GRID)
        ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.show()


# %% [markdown]
# Results (hotel 1, January 2022 dropped from every arm, MAE in euros).
#
# LASSO, 12 expanding folds over 2024. Calendar only (no feature has weight):
#   MAE 21.49. Best penalty: 18.30 (27 features). One standard error from the
#   best: 19.68 (6 features). The standard error is 1.70 and single folds swing
#   by about 7, so the curve is noisy. 22 of 28 features had zero weight; three
#   more were dropped before the LASSO for being nearly constant.
# Shortlist (weight in euros per standard deviation, folds that picked it):
#   avg_lead_on_books +9.8 (12), rooms_on_books +3.8 (12), cancel_lead_time +1.6
#   (12), trend_years -4.1 (9), night_before_holiday +0.8 (10), rate_last_year
#   +0.8 (12). They are also the first six to enter as the penalty loosens.
#
# EBM on 2025. "vs baseline" is the average monthly change in MAE with its
# standard error, negative = better; "better" counts months of 12.
#
# arm                                 year MAE  2025 MAE  vs baseline    better
# baseline                            19.33     19.24
# + avg_lead_on_books                 18.29     18.14     -1.10 +- 0.77   8  keep
# + rooms_on_books                    17.90     17.92     -1.32 +- 1.05   6
# + cancel_lead_time                  18.26     18.41     -0.83 +- 0.93   7
# + trend_years                       31.41     28.14     +8.90 +- 6.13   2
# + night_before_holiday              18.96     18.69     -0.55 +- 0.27   8  keep
# + rate_last_year                    19.53     19.43     +0.19 +- 0.85   6
# + all six                           15.30     18.13     -1.11 +- 2.01   9
#
# Run after seeing the table above, so treat them as follow-ups:
# + both that were kept               17.97     18.03     -1.21 +- 0.76   8
# + all six except trend_years        16.99     17.03     -2.21 +- 1.16   8
# control: blank before 2023          20.06     19.96     +0.72 +- 0.46   5
#
# Notes. The rule for keeping a feature was fixed before the run: lower the
# monthly error by more than its standard error, be better in at least 7 of 12
# months, and not raise the year-test error. Only avg_lead_on_books and
# night_before_holiday pass. trend_years breaks the EBM because it can't
# extend a trend past the years it trained on (October 2025 is 69 euros worse).
# Year bias on the year test goes from +2.75 (baseline) to +6.06 with the
# six-minus-trend set: the model leans higher. Everything is measured at one
# horizon, 30 days before the night.
