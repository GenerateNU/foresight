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
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from candidates import build_candidates
from joblib import Parallel, delayed
from matplotlib.patches import Patch
from sklearn.linear_model import lasso_path

from foresight.services.ml.base import score
from foresight.services.ml.ebm import EBMModel

SCREEN_START, SCREEN_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")
MIN_FLAGGED_NIGHTS = 10
MAX_TOP_VALUE_SHARE = 0.95
MIN_FOLDS = 9  # of 12


# %%
# The candidate columns are built in candidates.py, so the screen and the backtest
# start from the same table. January 2022 is already dropped there.
c = await build_candidates()  # noqa: F704
nights, stay, y, weights = c.nights, c.stay, c.y, c.weights
z_all, holiday_flag = c.z, c.holiday_flag
x_base = c.model_inputs[["room_type", "day_of_week", "month"]]
candidates = c.table
GROUPS = c.groups
print(f"{len(nights)} priced nights, {stay.min().date()} to {stay.max().date()}")
print(f"{int(holiday_flag.sum())} holiday nights")
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
# Survivor grid: which features each of the 12 monthly tests picked.
BLUE, ORANGE = "#2a78d6", "#eb6834"  # validated colors, colorblind-safe pair
SURFACE, GRID, INK, MUTED = "#fcfcfb", "#e5e4e0", "#1f1e1d", "#52514e"

fold_weights = np.array([f[:, chosen] for f in fold_fits])  # months x features
use = [
    j
    for j, n in enumerate(names)
    if (fold_weights[:, j] != 0).any() and not n.endswith("_missing")
]
count = (fold_weights[:, use] != 0).sum(axis=0)
average = fold_weights[:, use].sum(axis=0) / np.maximum(count, 1)
order = np.lexsort((-np.abs(average), -count))  # most consistent first
labels = [names[use[k]] for k in order]

fig, ax = plt.subplots(figsize=(11, 0.38 * len(labels) + 2.4), facecolor=SURFACE)
for row, k in enumerate(order):
    for month in range(len(months)):
        w = fold_weights[month, use[k]]
        color = GRID if w == 0 else (BLUE if w > 0 else ORANGE)
        ax.add_patch(
            plt.Rectangle(
                (month, row), 1, 1, facecolor=color, edgecolor=SURFACE, linewidth=2
            )
        )
    ax.text(12.4, row + 0.5, f"{count[k]}/12", va="center", fontsize=9, color=INK)
    ax.text(13.7, row + 0.5, f"{average[k]:+.1f}", va="center", fontsize=9, color=INK)
    stays = table.loc[labels[row], "enters at"]
    ax.text(15.2, row + 0.5, f"{stays:.2f}", va="center", fontsize=9, color=INK)

for x_pos, head in [
    (12.4, "months\npicked"),
    (13.7, "avg weight\n(€ per SD)"),
    (15.2, "penalty\nsurvived"),
]:
    ax.text(x_pos, -0.35, head, va="bottom", fontsize=8, color=MUTED)

kept = int((count[order] >= MIN_FOLDS).sum())
ax.axhline(kept, color=MUTED, linewidth=1)
ax.text(
    0,
    kept + 0.45,
    f"above the line: picked in {MIN_FOLDS}+ of 12 months",
    fontsize=8,
    color=MUTED,
    va="center",
)

ax.set_xlim(0, 16.4)
ax.set_ylim(len(labels), 0)
ax.set_xticks([m + 0.5 for m in range(len(months))])
ax.set_xticklabels([m.strftime("%b") for m in months], fontsize=9, color=MUTED)
ax.set_yticks([r + 0.5 for r in range(len(labels))])
ax.set_yticklabels(labels, fontsize=9, color=INK)
ax.tick_params(length=0)
ax.xaxis.tick_top()
ax.spines[:].set_visible(False)
ax.set_facecolor(SURFACE)
ax.set_title(
    "Which features the LASSO picked in each monthly test of 2024",
    loc="left",
    color=INK,
)
ax.legend(
    handles=[
        Patch(color=BLUE, label="pushes the rate up"),
        Patch(color=ORANGE, label="pushes the rate down"),
        Patch(color=GRID, label="not picked that month"),
    ],
    loc="upper center",
    bbox_to_anchor=(0.4, -0.02),
    ncol=3,
    frameon=False,
)
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
    model = EBMModel()
    model.fit(
        x_all.loc[train, columns],
        y[train].reset_index(drop=True),
        sample_weight=weights[train],
    )
    predicted = model.predict(x_all.loc[test, columns])
    return {
        "arm": arm,
        "fold": "",
        **score(y[test].to_numpy(), predicted),
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

# %%
