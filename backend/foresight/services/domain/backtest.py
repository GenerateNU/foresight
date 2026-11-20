"""Backtest the pricing model: train on older nights, predict the newest ones.

Read-only; models are trained in memory and thrown away. Trains on every
night except the last `test_days`, as if it were trained that day, then
predicts those nights. For a hotel that trains on bookings the rows are booked
rooms, one per room per night (decision 0056), so scores are per room. The
inputs come from `pricing_model.training_data`, the same loader training uses,
so the backtest scores the model that would ship.

`run_backtest` scores one set of inputs; compare sets by running it once per set.
`run_tuning_backtest` scores the daily tune-up against the base (decision 0073).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.pricing_model import HOLDOUT_FRAC, training_data
from foresight.services.domain.tuning import (
    MIN_TUNE_NIGHTS,
    UNTOUCHED_DAYS,
    fit_correction,
)
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.base import score
from foresight.services.ml.baselines import recent_weekday_mean, same_weekday_last_year
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import FEATURES, INPUT_GROUPS, LEAD
from foresight.services.ml.weighting import combine_identical_rows

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.services.domain.pricing_model import TrainingData

# The model's prediction interval is (1 - ALPHA); `coverage` is scored against it.
ALPHA = 0.2

# Baselines the model is compared with: column in `nights` -> label.
BASELINES = {
    "last_year": "Same weekday last year",
    "recent_weekday": "Last 4 weeks, same weekday",
}


def in_feature_order(inputs: Sequence[str]) -> list[str]:
    """The inputs, without repeats, in FEATURES order."""
    chosen = set(inputs)
    return [f for f in FEATURES if f in chosen]


@dataclass(frozen=True, slots=True)
class BaselineScore:
    """A baseline scored on the test nights it could predict, beside the model."""

    nights: int  # test nights the baseline had history for
    metrics: dict[str, float | None]  # as BacktestResult.metrics; no coverage
    model_mae: float  # the model's MAE on those same nights
    skill: float | None  # 1 - model_mae / baseline mae; > 0 means the model wins


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Each test row's actual and predicted rate, and how far off they were."""

    hotel_name: str
    inputs: list[str]  # the features the model was trained on
    event_days: int | None  # event history the model saw; None means all of it
    # One row per booked room per night: stay_date, room_type, lead_days,
    # actual, predicted, low, high (the (1 - ALPHA) interval); with baselines,
    # also one column per BASELINES key (NaN where it had no history)
    rows: pd.DataFrame
    metrics: dict[str, float | None]  # mae, rmse, mape, r2, bias, coverage
    baselines: dict[str, BaselineScore]  # keyed like BASELINES; empty if not asked


@dataclass(frozen=True, slots=True)
class BacktestSplit:
    """A hotel's training rows, split at the cutoff. Holds no session."""

    hotel_name: str
    data: TrainingData
    cutoff: date
    seen: np.ndarray  # True for training rows, False for test rows


async def load_backtest(
    session: AsyncSession,
    hotel_id: int,
    *,
    test_days: int = 90,
    start: date | None = None,
) -> BacktestSplit:
    """Past training rows from `start`, split `test_days` before the newest.

    The database part of a backtest; `run_backtest` then needs none, so the
    caller can release its connection before the fit.

    Raises NotFoundError for an unknown hotel, and InvalidRequestError if
    there are no nights on one side of the cutoff.
    """
    hotel = await get_hotel(session, hotel_id)
    yesterday = date.today() - timedelta(days=1)
    data = await training_data(session, hotel, start=start, end=yesterday)
    if data.nights.empty:
        raise InvalidRequestError("no priced nights to backtest")
    cutoff = data.nights["stay_date"].max() - timedelta(days=test_days)
    seen = (data.nights["stay_date"] <= cutoff).to_numpy()
    if not seen.any():
        raise InvalidRequestError(
            f"no nights before the cutoff {cutoff}; use a smaller --test-days"
        )
    return BacktestSplit(hotel.name, data, cutoff, seen)


async def run_backtest(
    split: BacktestSplit,
    *,
    baselines: bool = False,
    inputs: Sequence[str] | None = None,
    event_days: int | None = None,
) -> BacktestResult:
    """Predicts the test rows with a model trained on the rest.

    `inputs` picks the features the model trains on; the default is every
    input the training data has, like the model that's served. With
    `baselines`, also scores the BASELINES on the same nights.

    Raises InvalidRequestError for a bad `event_days`.
    """
    if event_days is not None and event_days < 1:
        raise InvalidRequestError("--event-days must be at least 1")
    columns = in_feature_order(FEATURES if inputs is None else inputs)
    predicted, low, high = await _fit_predict(split, columns, event_days)
    rows = _test_rows(split, predicted, low, high, baselines=baselines)
    return BacktestResult(
        hotel_name=split.hotel_name,
        inputs=columns,
        event_days=event_days,
        rows=rows,
        metrics=score(rows["actual"], rows["predicted"], low, high),
        baselines={
            name: _score_baseline(rows, name) for name in BASELINES if baselines
        },
    )


async def _fit_predict(
    split: BacktestSplit, columns: list[str], event_days: int | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fits on the training rows' `columns`; predicts the test rows.

    Rows the model can't tell apart are merged before the fit, as training
    does (decision 0056).
    """
    x = split.data.x[columns]
    if event_days is not None:
        x = _limit_event_history(x, split, event_days)
    model = await _fit_seen(split.data, split.seen, x)
    return model.predict_interval(x[~split.seen])


async def _fit_seen(data: TrainingData, seen: np.ndarray, x: pd.DataFrame) -> EBMModel:
    """An EBM fit on the `seen` rows of `x`, weighted and merged as training is."""
    xc, yc, wc, _ = combine_identical_rows(
        x[seen], data.y[seen], data.weights[seen], data.nights.loc[seen, "stay_date"]
    )
    model = EBMModel(alpha=ALPHA, calibration_frac=HOLDOUT_FRAC)
    # CPU-bound for seconds; a thread keeps the event loop free.
    await asyncio.to_thread(model.fit, xc, yc, sample_weight=wc)
    return model


def _limit_event_history(
    x: pd.DataFrame, split: BacktestSplit, event_days: int
) -> pd.DataFrame:
    """Blanks the event inputs on nights more than `event_days` before the cutoff.

    As if event history only reached that far back: the test nights and the
    other inputs are untouched, so runs with different `event_days` differ
    only in how much event history the model learned from.
    """
    start = split.cutoff - timedelta(days=event_days)
    old = (split.data.nights["stay_date"] <= start).to_numpy()
    columns = [c for c in INPUT_GROUPS["events"] if c in x.columns]
    x = x.copy()
    x.loc[old, columns] = float("nan")
    return x


def _test_rows(
    split: BacktestSplit,
    predicted: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    *,
    baselines: bool,
) -> pd.DataFrame:
    """The test rows' actual and predicted rates, and the baselines' if asked.

    A baseline predicts a night, so it's built from each training night's
    average booked rate and scored against every booked room on the test
    night, as the model is (decision 0076).
    """
    nights, seen = split.data.nights, split.seen
    targets = nights.loc[~seen]
    result = pd.DataFrame(
        {
            "stay_date": targets["stay_date"],
            "room_type": targets["room_type"],
            LEAD: split.data.x.loc[~seen, LEAD].to_numpy(),
            "actual": split.data.y[~seen],
            "predicted": predicted,
            "low": low,
            "high": high,
        }
    )
    if baselines:
        # Baselines see only nights up to the cutoff, as the model did.
        history = (
            nights.loc[seen]
            .assign(rate=split.data.y[seen])
            .groupby(["stay_date", "room_type"], as_index=False)["rate"]
            .mean()
        )
        result["last_year"] = same_weekday_last_year(history, targets)
        result["recent_weekday"] = recent_weekday_mean(history, targets, split.cutoff)
    return result


def _score_baseline(nights: pd.DataFrame, column: str) -> BaselineScore:
    """Scores a baseline and the model on the nights the baseline could predict."""
    covered = nights.loc[nights[column].notna()]
    if covered.empty:
        return BaselineScore(nights=0, metrics={}, model_mae=float("nan"), skill=None)
    metrics = score(covered["actual"], covered[column])
    model_mae = score(covered["actual"], covered["predicted"])["mae"]
    assert model_mae is not None and metrics["mae"] is not None
    skill = 1 - model_mae / metrics["mae"] if metrics["mae"] > 0 else None
    return BaselineScore(
        nights=len(covered), metrics=metrics, model_mae=model_mae, skill=skill
    )


# --- Tune-up backtest (decision 0073) ---

# Days of manager feedback the tuning backtest tries, by default.
TUNING_SIZES = (5, 10, 20, 30)
# Fixes which days a partial manager prices, so runs are comparable.
MANAGER_SEED = 0
# Nights a ManagerRule can pick out: name -> does a feature row match.
RULE_NIGHTS = {
    "all": lambda x: np.ones(len(x), dtype=bool),
    "weekend": lambda x: x["day_of_week"].isin([4, 5]).to_numpy(),  # Fri, Sat
    "weekday": lambda x: ~x["day_of_week"].isin([4, 5]).to_numpy(),
    # Big events: nearly every night with event data has some small ones.
    "events": lambda x: (x["big_event_count"] > 0).to_numpy(),
}


@dataclass(frozen=True, slots=True)
class ManagerRule:
    """A synthetic manager's habit: `pct` on top of the base on `nights`.

    E.g. ManagerRule("weekend", 0.15): every Friday and Saturday 15% above
    what the base model says, every other night as the base says. The base
    can't know this, so the tune-up is the only way to learn it (decision 0074).
    """

    nights: str  # a key of RULE_NIGHTS
    pct: float  # 0.15 is +15%

    def __post_init__(self) -> None:
        if self.nights not in RULE_NIGHTS:
            raise InvalidRequestError(
                f"unknown manager-rule nights {self.nights!r}; "
                f"use one of {', '.join(RULE_NIGHTS)}"
            )

    def matches(self, x: pd.DataFrame) -> np.ndarray:
        return RULE_NIGHTS[self.nights](x)

    def apply(self, x: pd.DataFrame, base_pred: np.ndarray) -> np.ndarray:
        """The rate this manager sets on each row of x."""
        return np.where(self.matches(x), base_pred * (1 + self.pct), base_pred)

    def __str__(self) -> str:
        return f"{self.nights}{self.pct:+.0%}"


@dataclass(frozen=True, slots=True)
class TuningRow:
    """The tune-up after `feedback_days` days of manager rates, on the eval nights."""

    feedback_days: int
    feedback_nights: int  # rows (night x room type) the manager "priced"
    untouched_nights: int  # rows learned as "no change" (decision 0072)
    feedback_dates: tuple[date, date]  # first and last feedback night
    untouched_dates: tuple[date, date] | None  # None when there were none
    # As BacktestResult.metrics, no coverage; empty when skipped.
    manager_only: dict[str, float | None]  # correction fit on the manager's rates
    with_untouched: dict[str, float | None]  # plus untouched nights: what ships
    skill_manager_only: float | None  # 1 - tuned MAE / base MAE; > 0 beats the base
    skill_with_untouched: float | None
    mean_correction: float | None  # shipped variant, over the eval nights
    skipped: str | None = None  # why the size wasn't tuned
    # With a ManagerRule only, shipped variant on the eval nights: mean
    # correction / mean gap the rule adds, on the nights it matches (1 is
    # all of it learned), and the mean correction on the nights it doesn't
    # match (0 is right: they should not move).
    recovery: float | None = None
    drift: float | None = None


@dataclass(frozen=True, slots=True)
class TuningBacktestResult:
    """The base model and each tune-up size, scored on the same eval nights."""

    hotel_name: str
    train_start: date  # the base trains on nights from here
    cutoff: date  # to here
    eval_start: date  # first scored night: after max(sizes) priced days
    eval_end: date
    eval_nights: int  # one row per night, booked rooms averaged (0076)
    base: dict[str, float | None]  # the untuned model on the eval nights
    rows: list[TuningRow]
    rule: ManagerRule | None  # None: the recorded rate is the manager's
    manager_share: float  # share of feedback days the manager priced
    # Every held-out night: stay_date, room_type, actual, base, day (its
    # priced-day number after the cutoff; the first max(sizes) are feedback),
    # scored, and per tuned size N, mgr_only_N and tuned_N (what ships),
    # NaN except on scored nights.
    nights: pd.DataFrame


@dataclass(frozen=True, slots=True)
class TuningSplit:
    """A hotel's training rows split for the tuning backtest. Holds no session."""

    hotel_name: str
    data: TrainingData
    cutoff: date  # the last training day
    seen: np.ndarray  # True for rows the base trains on
    days_after: list[date]  # the held-out priced days, oldest first


async def load_tuning_backtest(
    session: AsyncSession,
    hotel_id: int,
    *,
    test_days: int = 60,
    start: date | None = None,
) -> TuningSplit:
    """Past training rows from `start`, split `test_days` priced days before the
    newest. Counts priced days, not calendar days, so gaps in the data don't
    leave the feedback or scored nights empty.

    The database part; `run_tuning_backtest` needs none, so the caller can
    release its connection before the fits.

    Raises NotFoundError for an unknown hotel, and InvalidRequestError if
    there are too few priced days.
    """
    hotel = await get_hotel(session, hotel_id)
    yesterday = date.today() - timedelta(days=1)
    data = await training_data(session, hotel, start=start, end=yesterday)
    days = sorted(set(data.nights["stay_date"]))
    if len(days) <= test_days:
        raise InvalidRequestError(
            f"only {len(days)} priced days; use a smaller --test-days"
        )
    cutoff = days[-test_days - 1]
    seen = (data.nights["stay_date"] <= cutoff).to_numpy()
    return TuningSplit(hotel.name, data, cutoff, seen, days[-test_days:])


async def run_tuning_backtest(
    split: TuningSplit,
    *,
    sizes: Sequence[int] = TUNING_SIZES,
    rule: ManagerRule | None = None,
    manager_share: float = 1.0,
) -> TuningBacktestResult:
    """Does the tune-up beat the base model, and after how many days of feedback?

    The base trains on every row before the held-out days, as if it went live
    then. The held-out nights are one row each: on booked rooms, the night's
    average booked rate, booked the day before (decision 0076). For each size
    N, the rates of the first N held-out days stand in for the manager's, the
    correction is fit on them (with and without the untouched nights of
    decision 0072), and both are scored, with the base, on the nights after
    the first max(sizes) days, the same nights for every size.

    The manager reviews `manager_share` of the feedback days, picked at
    random, and sets a rate on each night of them; the nights they didn't
    review are past nights left alone, which the tune-up learns as "no
    change", as `tune` does. With a `rule`, the manager is synthetic: their
    rate is the base's with the rule applied, on feedback and scored nights
    alike, and on a reviewed day they set a rate only where the rule changes
    it, accepting the rest (decision 0074).

    Raises InvalidRequestError for bad sizes or if no nights are left to score.
    """
    sizes = sorted(set(sizes))
    if not sizes or sizes[0] < 1:
        raise InvalidRequestError("--sizes must be positive numbers of days")
    if not 0 < manager_share <= 1:
        raise InvalidRequestError("--manager-share must be above 0 and at most 1")
    days_after = split.days_after
    if len(days_after) <= sizes[-1]:
        raise InvalidRequestError(
            f"--test-days {len(days_after)} leaves no days to score after "
            f"{sizes[-1]} days of feedback; use more --test-days or smaller --sizes"
        )

    base = await _fit_seen(split.data, split.seen, split.data.x)
    held, x, y = _held_out_nights(split.data, split.seen)
    stay = held["stay_date"]
    rank = stay.map({d: i for i, d in enumerate(days_after, start=1)}).to_numpy()
    base_all = base.predict(x)
    if rule is not None:  # the synthetic manager's rate replaces the recorded one
        y = rule.apply(x, base_all)
    # Which feedback days the manager reviewed; the rest they left alone.
    pick = np.random.default_rng(MANAGER_SEED).random(len(days_after)) < manager_share
    priced = pick[rank - 1]
    if rule is not None:  # a synthetic manager accepts nights the rule leaves
        priced &= rule.matches(x)
    trained_on = set(split.data.nights.loc[split.seen, "room_type"])
    known_room = held["room_type"].isin(trained_on).to_numpy()

    scored = rank > sizes[-1]
    x_eval = x[scored]
    base_pred = base_all[scored]
    base_metrics = score(y[scored], base_pred)
    base_mae = base_metrics["mae"]
    nights = pd.DataFrame(
        {
            "stay_date": stay.to_numpy(),
            "room_type": held["room_type"].to_numpy(),
            "actual": y,
            "base": base_all,
            "day": rank,
            "scored": scored,
        }
    )

    rows = []
    for n in sizes:
        # "Today" is the day after the last feedback day. Untouched nights
        # are feedback days the manager didn't price, within UNTOUCHED_DAYS
        # back: past nights left alone (decision 0074).
        today = days_after[n - 1] + timedelta(days=1)
        window = rank <= n
        manager = window & priced
        horizon = (stay >= today - timedelta(days=UNTOUCHED_DAYS)).to_numpy()
        untouched = window & ~priced & horizon & known_room
        used = {
            "feedback_days": n,
            "feedback_nights": int(manager.sum()),
            "untouched_nights": int(untouched.sum()),
            "feedback_dates": (days_after[0], days_after[n - 1]),
            "untouched_dates": (
                (stay[untouched].min(), stay[untouched].max())
                if untouched.any()
                else None
            ),
        }
        if manager.sum() < MIN_TUNE_NIGHTS:
            rows.append(
                TuningRow(
                    **used,
                    manager_only={},
                    with_untouched={},
                    skill_manager_only=None,
                    skill_with_untouched=None,
                    mean_correction=None,
                    skipped=f"{int(manager.sum())} nights; need {MIN_TUNE_NIGHTS}",
                )
            )
            continue
        y_manager = pd.Series(y[manager])
        only = await asyncio.to_thread(fit_correction, base, x[manager], y_manager)
        # The manager was shown the base here, so that is the untouched
        # nights' shown rate (decision 0078).
        both = await asyncio.to_thread(
            fit_correction,
            base,
            x[manager],
            y_manager,
            x[untouched],
            pd.Series(base_all[untouched]),
        )
        only_pred, both_pred = only.predict(x_eval), both.predict(x_eval)
        only_metrics = score(y[scored], only_pred)
        both_metrics = score(y[scored], both_pred)
        for column, pred in ((f"mgr_only_{n}", only_pred), (f"tuned_{n}", both_pred)):
            nights[column] = float("nan")
            nights.loc[scored, column] = pred
        correction = both.correction(x_eval)
        recovery = drift = None
        if rule is not None:
            hit = rule.matches(x_eval)
            gap = (y[scored] - base_pred)[hit].mean() if hit.any() else 0.0
            recovery = float(correction[hit].mean() / gap) if gap else None
            drift = float(correction[~hit].mean()) if (~hit).any() else None
        rows.append(
            TuningRow(
                **used,
                manager_only=only_metrics,
                with_untouched=both_metrics,
                skill_manager_only=_skill(only_metrics["mae"], base_mae),
                skill_with_untouched=_skill(both_metrics["mae"], base_mae),
                mean_correction=float(correction.mean()),
                recovery=recovery,
                drift=drift,
            )
        )

    eval_days = stay[scored]
    return TuningBacktestResult(
        hotel_name=split.hotel_name,
        train_start=split.data.nights.loc[split.seen, "stay_date"].min(),
        cutoff=split.cutoff,
        eval_start=eval_days.min(),
        eval_end=eval_days.max(),
        eval_nights=int(scored.sum()),
        base=base_metrics,
        rows=rows,
        nights=nights,
        rule=rule,
        manager_share=manager_share,
    )


def _held_out_nights(
    data: TrainingData, seen: np.ndarray
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """One row per held-out room type and night: its key, inputs and rate.

    A night has many booked rooms; the manager prices the night, not a
    booking, so the night's rate is its average booked rate and its inputs are
    its first room's with days ahead set to 1, booked the day before (decision
    0076). Oldest night first.
    """
    held = ~seen
    rows = data.nights.loc[held, ["stay_date", "room_type"]].reset_index(drop=True)
    x = data.x.loc[held].reset_index(drop=True)
    y = data.y.loc[held].reset_index(drop=True).astype(float)
    group = rows.groupby(["stay_date", "room_type"], sort=False).ngroup().to_numpy()
    first = pd.Series(np.arange(len(rows))).groupby(group).first().to_numpy()
    x_nights = x.iloc[first].reset_index(drop=True)
    if LEAD in x_nights:
        x_nights[LEAD] = 1
    rate = y.groupby(group).mean().to_numpy()
    return rows.iloc[first].reset_index(drop=True), x_nights, rate


def _skill(mae: float | None, base_mae: float | None) -> float | None:
    """1 - mae / base_mae; above 0, the tune-up beats the base."""
    if mae is None or not base_mae:
        return None
    return 1 - mae / base_mae
