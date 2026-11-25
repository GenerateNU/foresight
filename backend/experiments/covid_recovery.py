"""COVID recovery in early 2022, for ticket #139: does treating it help the baseline?"""

# %% [markdown]
# Rules, fixed before running anything (same as baseline_testing.py).
# Baseline: calendar plus Irish public holidays, EBM, hotel 1, data to 2025-12-31.
# Judged on the year test (train 2022-2024, test 2025) and the rolling test
# (each month of 2024-2025, trained on every night before it). Each variant is
# compared with the baseline month by month, on the same test nights.

# %%
from datetime import date, timedelta

import numpy as np
import pandas as pd
from dateutil.easter import easter

from foresight.database.session import async_session_factory
from foresight.services.domain.backtest import in_feature_order, score
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.training_data import training_data
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import INPUT_GROUPS

HOTEL_ID = 1
DATA_END = date(2025, 12, 31)
# Months of 2022 whose rate is well below the same month in later years.
RECOVERY_END = pd.Timestamp("2022-06-01")


async def load(end=DATA_END):
    async with async_session_factory() as session:
        hotel = await get_hotel(session, HOTEL_ID)
        return await training_data(session, hotel, start=None, end=end)


data = await load()  # noqa: F704
stay = pd.to_datetime(data.rows["stay_date"])
y = data.y.astype(float).reset_index(drop=True)


# %%
# Average rate per month and year. 2022 vs later = 2022 / mean of 2023-2025.
rates = pd.DataFrame({"month": stay.dt.month, "year": stay.dt.year, "rate": y})
by_month = rates.pivot_table(index="month", columns="year", values="rate")
by_month["2022 vs later"] = by_month[2022] / by_month[[2023, 2024, 2025]].mean(axis=1)
print(by_month.round(2).to_string())


# %%
# Same holiday list as baseline_testing.py.
def irish_public_holidays(year: int) -> set[date]:
    def first_monday(month: int) -> date:
        d = date(year, month, 1)
        return d + timedelta(days=(7 - d.weekday()) % 7)

    def last_monday(month: int) -> date:
        d = date(year, month + 1, 1) - timedelta(days=1)
        return d - timedelta(days=d.weekday())

    days = {
        date(year, 1, 1),
        date(year, 3, 17),
        easter(year) + timedelta(days=1),
        first_monday(5),
        first_monday(6),
        first_monday(8),
        last_monday(10),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    if year >= 2023:
        feb1 = date(year, 2, 1)
        days.add(feb1 if feb1.weekday() == 4 else first_monday(2))
    return days


HOLIDAYS = set().union(*(irish_public_holidays(y) for y in range(2022, 2026)))
BASELINE_COLUMNS = in_feature_order([*INPUT_GROUPS["calendar"], "is_public_holiday"])

x = data.x.copy()
x["is_public_holiday"] = data.rows["stay_date"].isin(HOLIDAYS).astype(float)
recovering = (stay < RECOVERY_END).to_numpy()
x["covid_recovery"] = recovering.astype(float)
# Months since Jan 2022, flat from June 2022: a ramp instead of an on/off flag.
x["recovery_months"] = np.minimum((stay.dt.year - 2022) * 12 + stay.dt.month - 1, 5)
x["year"] = stay.dt.year.to_numpy()


# %%
# Each variant: (extra columns, training rows kept, weight multiplier).
# A multiplier of None means time decay, set per fold from its cutoff.
everything = np.ones(len(y), dtype=bool)
VARIANTS = {
    "baseline": ([], everything, 1.0),
    "drop Jan-Feb 2022": ([], (stay >= "2022-03-01").to_numpy(), 1.0),
    "drop Jan-May 2022": ([], ~recovering, 1.0),
    "drop all 2022": ([], (stay >= "2023-01-01").to_numpy(), 1.0),
    "flag Jan-May 2022": (["covid_recovery"], everything, 1.0),
    "recovery ramp": (["recovery_months"], everything, 1.0),
    "down-weight Jan-May 2022 x0.2": ([], everything, np.where(recovering, 0.2, 1.0)),
    "year as input": (["year"], everything, 1.0),
    "time decay, 1-year half-life": ([], everything, None),
}


def run_fold(variant, start, end):
    """Fits the variant on nights before `start`, scores the nights in [start, end)."""
    extra, keep, multiplier = VARIANTS[variant]
    columns = [*BASELINE_COLUMNS, *extra]
    train = (stay < start).to_numpy() & keep
    test = ((stay >= start) & (stay < end)).to_numpy()
    if multiplier is None:
        multiplier = 0.5 ** ((pd.Timestamp(start) - stay).dt.days.to_numpy() / 365)
    weights = data.weights * np.broadcast_to(multiplier, len(y))

    model = EBMModel()
    model.fit(
        x.loc[train, columns],
        y[train].reset_index(drop=True),
        sample_weight=weights[train],
    )
    predicted = model.predict(x.loc[test, columns])
    return score(y[test].to_numpy(), predicted)


# %%
# Year test plus the 24 rolling months, for every variant. About 2 s per fit.
FOLDS = {"year 2025": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01"))}
for month_start in pd.date_range("2024-01-01", "2025-12-01", freq="MS"):
    FOLDS[month_start.strftime("%Y-%m")] = (
        month_start,
        month_start + pd.offsets.MonthBegin(1),
    )

results = pd.DataFrame(
    [
        {"variant": variant, "fold": fold, **run_fold(variant, start, end)}
        for variant in VARIANTS
        for fold, (start, end) in FOLDS.items()
    ]
)


# %%
def season(month):
    """Dec-Feb winter, Mar-May spring, Jun-Aug summer, Sep-Nov autumn."""
    return ["Winter", "Spring", "Summer", "Autumn"][(month % 12) // 3]


year_test = results[results["fold"] == "year 2025"].set_index("variant")
rolling = results[results["fold"] != "year 2025"].copy()
rolling["season"] = [season(int(f[5:])) for f in rolling["fold"]]
base = rolling[rolling["variant"] == "baseline"].set_index("fold")["mae"]

rows = []
for variant, runs in rolling.groupby("variant", sort=False):
    # Positive = worse than the baseline on the same month.
    diff = runs.set_index("fold")["mae"] - base
    in_2024 = diff.index.str.startswith("2024")
    rows.append(
        {
            "variant": variant,
            "year MAE": year_test.loc[variant, "mae"],
            "year bias": year_test.loc[variant, "bias"],
            "rolling MAE": runs["mae"].mean(),
            "vs baseline": diff.mean(),
            "std error": diff.std() / len(diff) ** 0.5,
            "2024": diff[in_2024].mean(),
            "2025": diff[~in_2024].mean(),
            "months better": int((diff < 0).sum()),
        }
    )
print(pd.DataFrame(rows).round(2).to_string(index=False))

seasons = ["Winter", "Spring", "Summer", "Autumn"]
shown = ["baseline", "drop Jan-May 2022", "flag Jan-May 2022", "drop all 2022"]
bias = rolling.pivot_table(index="season", columns="variant", values="bias")
print("\nAverage bias by season (positive = predicts too high):")
print(bias.loc[seasons, shown].round(2).to_string())

# %% [markdown]
# Results (hotel 1, MAE in euros; "vs baseline" is the average monthly
# difference over the 24 rolling months with its standard error, positive =
# worse; "better" is how many of the 24 months beat the baseline).
#
# variant                        year   rolling  vs baseline    better
# baseline                       18.66  19.51
# drop Jan-Feb 2022              19.76  20.02    +0.51 ± 0.32   10/24
# drop Jan-May 2022              20.68  20.90    +1.39 ± 0.49    6/24
# drop all 2022                  20.45  20.63    +1.12 ± 0.55    7/24
# flag Jan-May 2022              20.24  20.60    +1.08 ± 0.47   12/24
# recovery ramp                  20.35  20.77    +1.26 ± 0.46    5/24
# down-weight Jan-May 2022 x0.2  19.94  20.25    +0.74 ± 0.36    9/24
# year as input                  18.62  19.55    +0.04 ± 0.49   11/24
# time decay, 1-year half-life   19.27  19.74    +0.23 ± 0.27   12/24
#
# "Better" counts any month with a lower error, however small, so a variant can
# win about half the months and still lose on average: the flag is better in 12
# of 24 months, by a few cents in summer and autumn, but 1-3 euros worse in
# winter and spring.
#
# Every way of removing the 2022 dip makes the model worse, mostly in winter
# and spring: dropping Jan-May 2022 moves the average bias from +1.9 to +9.8
# in winter and from -2.7 to +7.8 in spring.
#
# Why: off-season rates peaked in 2023 and have fallen since (January 106,
# 97, 91; February 121, 116, 104). The low 2022 months pull the model's month
# averages down to about where 2024 and 2025 landed (January: 92 with 2022,
# 101 without, actual 2025 91). 2022 helps by coincidence, not because the
# recovery months are good data.
#
# Year as input and time decay, the two ways of telling the model "recent
# years count more", are no better than the baseline overall.
#
# Decision for now: keep 2022 in, untreated. The real gap is that the model
# can't see the current price level. Test recent-history features (rate on the
# same weekday a few weeks back, lagged at least 30 days; rate on the same
# night last year). If one of them works, rerun this file: once the model can
# see the level, the 2022 dip may start to hurt instead of help.
