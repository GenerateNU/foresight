"""Choosing the backtest's inputs: groups and `--inputs`. No DB."""

from __future__ import annotations

import argparse
from collections import Counter

import pytest

from foresight.cli import _describe_inputs, _parse_inputs
from foresight.services.ml.features import FEATURES, INPUT_GROUPS


def test_groups_cover_every_input_once() -> None:
    grouped = Counter(c for columns in INPUT_GROUPS.values() for c in columns)
    assert sorted(grouped) == sorted(FEATURES)
    assert set(grouped.values()) == {1}


def test_parse_expands_groups_and_keeps_feature_order() -> None:
    assert _parse_inputs("month,calendar") == ["room_type", "day_of_week", "month"]


def test_parse_mixes_groups_and_features_without_repeats() -> None:
    assert _parse_inputs(" month , day_of_week,month ") == ["day_of_week", "month"]


@pytest.mark.parametrize("text", ["calendar,bogus", "", " , "])
def test_parse_rejects_unknown_or_empty(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_inputs(text)


def test_describe_names_whole_groups() -> None:
    assert _describe_inputs(list(FEATURES)) == "all inputs"
    assert _describe_inputs(_parse_inputs("month,day_of_week")) == "day_of_week, month"
