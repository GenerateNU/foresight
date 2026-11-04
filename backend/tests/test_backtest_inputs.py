"""Choosing the backtest's inputs: groups, `--inputs` and `--event-days`. No DB."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from foresight.cli import _describe_inputs, _parse_inputs
from foresight.services.domain.backtest import (
    _limit_event_history,
    _Split,
    in_feature_order,
)
from foresight.services.domain.pricing_model import TrainingData
from foresight.services.ml.features import (
    BACKTEST_INPUTS,
    BOOKING_INPUTS,
    FEATURES,
    INPUT_GROUPS,
)


def test_groups_cover_every_input_once() -> None:
    grouped = Counter(c for columns in INPUT_GROUPS.values() for c in columns)
    assert sorted(grouped) == sorted(BACKTEST_INPUTS)
    assert set(grouped.values()) == {1}


def test_booking_inputs_are_not_served() -> None:
    assert not set(BOOKING_INPUTS) & set(FEATURES)


def test_parse_expands_groups_and_keeps_feature_order() -> None:
    got = _parse_inputs("weather,calendar")
    assert got == in_feature_order(INPUT_GROUPS["calendar"] + INPUT_GROUPS["weather"])
    assert got[:3] == ["room_type", "day_of_week", "month"]


def test_parse_mixes_groups_and_features_without_repeats() -> None:
    got = _parse_inputs(" calendar , precip_mm,month ")
    assert got == ["room_type", "day_of_week", "month", "precip_mm"]


@pytest.mark.parametrize("text", ["calendar,bogus", "", " , "])
def test_parse_rejects_unknown_or_empty(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_inputs(text)


def test_parse_accepts_the_bookings_group() -> None:
    assert _parse_inputs("calendar,bookings")[-2:] == BOOKING_INPUTS


def test_describe_names_whole_groups() -> None:
    assert _describe_inputs(list(FEATURES)) == "all inputs"
    assert (
        _describe_inputs(_parse_inputs("calendar,precip_mm")) == "calendar, precip_mm"
    )


def _split(days: int, cutoff_day: int) -> _Split:
    """`days` nights from 1 Sep 2026, every input 1.0, cut after `cutoff_day`."""
    stay = [date(2026, 9, 1) + timedelta(days=i) for i in range(days)]
    data = TrainingData(
        nights=pd.DataFrame({"stay_date": stay}),
        x=pd.DataFrame(1.0, index=range(days), columns=FEATURES),
        y=pd.Series(100.0, index=range(days)),
        weights=np.ones(days),
        events_fetched=set(stay),
    )
    cutoff = stay[cutoff_day]
    return _Split(data, cutoff, np.array([d <= cutoff for d in stay]))


def test_event_days_blanks_only_old_event_inputs() -> None:
    split = _split(10, cutoff_day=6)  # cutoff 7 Sep; 8-10 Sep are test nights
    got = _limit_event_history(split.data.x, split, event_days=3)

    events = INPUT_GROUPS["events"]
    others = [c for c in FEATURES if c not in events]
    assert got.loc[:3, events].isna().all().all()  # 1-4 Sep: over 3 days back
    assert got.loc[4:, events].notna().all().all()  # 5-7 Sep and the test nights
    assert got[others].notna().all().all()  # calendar and weather untouched


def test_event_days_leaves_the_original_alone() -> None:
    split = _split(10, cutoff_day=6)
    _limit_event_history(split.data.x, split, event_days=3)
    assert split.data.x.notna().all().all()


def test_event_days_without_event_inputs_changes_nothing() -> None:
    split = _split(10, cutoff_day=6)
    x = split.data.x[INPUT_GROUPS["calendar"] + INPUT_GROUPS["weather"]]
    pd.testing.assert_frame_equal(_limit_event_history(x, split, event_days=3), x)
