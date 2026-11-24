"""Baseline testing for ticket #139: year test and rolling test."""

# %% [markdown]
# Rules, fixed before running anything.
# Year test:    train 2022-01-01 to 2024-12-31, test all of 2025.
# Rolling test: one 30-day test window per month, 2024-01 to 2025-12,
#               trained on every night before each window (expanding).
# Data stops at 2025-12-31: 2026 has only 12 nights a month, so it's left out.

# %%
from datetime import date, timedelta

import matplotlib.pyplot as plt
import pandas as pd
from dateutil.easter import easter
from matplotlib.patches import Patch

from foresight.database.session import async_session_factory
from foresight.services.domain.backtest import in_feature_order, score
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.pricing_model import training_data
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import INPUT_GROUPS

HOTEL_ID = 1
DATA_END = date(2025, 12, 31)
# Calendar plus the public-holiday flag, which we build ourselves below.
BASELINE_COLUMNS = in_feature_order([*INPUT_GROUPS["calendar"], "is_public_holiday"])


# Load the training data from the database
async def load(end=DATA_END):
    async with async_session_factory() as session:
        hotel = await get_hotel(session, HOTEL_ID)
        return await training_data(session, hotel, start=None, end=end)


# Load the training data and display basic information about it
# %%
data = await load()  # noqa: F704
dates = data.nights["stay_date"]
print(f"{len(data.nights)} priced nights, {dates.min()} to {dates.max()}")


# Irish public holidays for the years 2022 to 2025 are calculated and added to
# the dataset.
# %%
def irish_public_holidays(year: int) -> set[date]:
    def first_monday(month: int) -> date:
        d = date(year, month, 1)
        return d + timedelta(days=(7 - d.weekday()) % 7)

    def last_monday(month: int) -> date:
        d = date(year, month + 1, 1) - timedelta(days=1)  # last day of the month
        return d - timedelta(days=d.weekday())

    days = {
        date(year, 1, 1),  # New Year's Day
        date(year, 3, 17),  # St Patrick's Day
        easter(year) + timedelta(days=1),  # Easter Monday
        first_monday(5),  # May bank holiday
        first_monday(6),  # June bank holiday
        first_monday(8),  # August bank holiday
        last_monday(10),  # October bank holiday
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # St Stephen's Day
    }
    if year >= 2023:  # St Brigid's Day: first Monday of Feb, or Feb 1 if a Friday
        feb1 = date(year, 2, 1)
        days.add(feb1 if feb1.weekday() == 4 else first_monday(2))
    return days


HOLIDAYS = set().union(*(irish_public_holidays(y) for y in range(2022, 2026)))

# Add the public holiday flag to the training data
x = data.x.copy()
x["is_public_holiday"] = data.nights["stay_date"].isin(HOLIDAYS).astype(float)
print(f"{int(x['is_public_holiday'].sum())} holiday nights flagged")


# %%
def run_fold(train, test, data=data, x=x, columns=BASELINE_COLUMNS):
    """Fits on the `train` nights, predicts the `test` nights, returns the scores.

    `train` and `test` are True/False arrays with one entry per night in `data`.
    """
    inputs = x[columns]
    model = EBMModel()
    model.fit(inputs[train], data.y[train], sample_weight=data.weights[train])
    predicted = model.predict(inputs[test])
    scores = score(data.y[test], predicted)
    nights = pd.DataFrame(
        {
            "stay_date": data.nights.loc[test, "stay_date"],
            "actual": data.y[test],
            "predicted": predicted,
        }
    )
    return scores, nights


# %%
# Sanity check: copy the real backtest's split and compare with `just backtest`.
check = await load(end=date.today() - timedelta(days=1))  # noqa: F704
calendar = in_feature_order(INPUT_GROUPS["calendar"])

cutoff = check.nights["stay_date"].max() - timedelta(days=30)
seen = (check.nights["stay_date"] <= cutoff).to_numpy()

check_scores, _ = run_fold(seen, ~seen, data=check, x=check.x, columns=calendar)
print(f"{(~seen).sum()} test nights, MAE {check_scores['mae']:.2f}")
print(f"RMSE {check_scores['rmse']:.2f}")


# %%
# Year test: train on 2022-2024, test on all of 2025.
stay = data.nights["stay_date"]
# drop January 2022 as not all features have that data
not_jan_2022 = ~((stay >= date(2022, 1, 1)) & (stay <= date(2022, 1, 31))).to_numpy()
train = (stay < date(2025, 1, 1)).to_numpy() & not_jan_2022
test = (stay >= date(2025, 1, 1)).to_numpy()

year_scores, year_nights = run_fold(train, test)
print(f"train: {train.sum()} nights, test: {test.sum()} nights")
print(year_scores)

# %%
BLUE, ORANGE = "#2a78d6", "#eb6834"  # validated colors, colorblind-safe pair
SURFACE, GRID = "#fcfcfb", "#e5e4e0"
SEASON_COLORS = {
    "Winter": "#2a78d6",
    "Spring": "#1baf7a",
    "Summer": "#eda100",
    "Autumn": "#e87ba4",
}


def season(month):
    """Dec-Feb winter, Mar-May spring, Jun-Aug summer, Sep-Nov autumn."""
    return list(SEASON_COLORS)[(month % 12) // 3]


def tidy(ax):
    """The look both charts share: light background, soft grid, no top/right box."""
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID)
    ax.spines[["top", "right"]].set_visible(False)


dates = pd.to_datetime(year_nights["stay_date"])
error = (year_nights["predicted"] - year_nights["actual"]).abs()
monthly_error = error.groupby(dates.dt.month).mean()

fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 7), facecolor=SURFACE)
top.plot(dates, year_nights["actual"], color=BLUE, linewidth=1.2, label="Actual")
top.plot(
    dates, year_nights["predicted"], color=ORANGE, linewidth=1.2, label="Predicted"
)
top.set_title("2025: actual vs predicted rate")
top.legend(frameon=False)

bottom.bar(monthly_error.index, monthly_error.values, color=BLUE)
bottom.set_xticks(range(1, 13))
bottom.set_title("Average error by month (how far off the rate was)")
bottom.set_xlabel("Month of 2025")

for ax in (top, bottom):
    tidy(ax)

plt.tight_layout()
plt.show()


# %%
# Rolling test: test each month of 2024-2025, training on every night before it.
rows = []
for month_start in pd.date_range("2024-01-01", "2025-12-01", freq="MS"):
    start = month_start.date()
    end = (month_start + pd.offsets.MonthBegin(1)).date()
    # January 2022 is left out of training, so every comparison uses the same nights.
    fit = (stay < start).to_numpy() & not_jan_2022
    holdout = ((stay >= start) & (stay < end)).to_numpy()
    month_scores, _ = run_fold(fit, holdout)
    rows.append({"month": start, "nights": holdout.sum(), **month_scores})

rolling = pd.DataFrame(rows)
print(
    rolling[["month", "nights", "mae", "rmse", "bias"]].round(2).to_string(index=False)
)
in_2025 = rolling[rolling["month"] >= date(2025, 1, 1)]
print(
    f"2024-2025 average MAE {rolling['mae'].mean():.2f}, "
    f"spread {rolling['mae'].std():.2f}"
)
print(f"2025 only: average MAE {in_2025['mae'].mean():.2f} (year test was 18.66)")


# %%
fig, ax = plt.subplots(figsize=(10, 4), facecolor=SURFACE)
average = rolling["mae"].mean()

colors = [SEASON_COLORS[season(m.month)] for m in rolling["month"]]
ax.bar(range(len(rolling)), rolling["mae"], color=colors)
ax.axhline(average, color="#52514e", linewidth=1, linestyle="--")
ax.text(len(rolling) - 0.5, average, "average", ha="right", va="bottom")

ax.set_xticks(range(len(rolling)))
ax.set_xticklabels([m.strftime("%b %y") for m in rolling["month"]], rotation=90)
ax.set_title("Rolling test: average error per month (MAE)")
tidy(ax)

ax.legend(
    handles=[Patch(color=c, label=s) for s, c in SEASON_COLORS.items()],
    frameon=False,
    ncol=4,
    loc="upper left",
)

plt.tight_layout()
plt.show()


# %%
rolling["season"] = [season(m.month) for m in rolling["month"]]
by_season = rolling.groupby("season").agg(
    months=("mae", "size"),
    avg_mae=("mae", "mean"),
    worst_mae=("mae", "max"),
    avg_bias=("bias", "mean"),
)
print(by_season.loc[list(SEASON_COLORS)].round(2))
