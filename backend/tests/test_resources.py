"""Measuring a fit's time and memory (decision 0046). No DB."""

from __future__ import annotations

from foresight.services.ml.resources import measure


def test_measure_fills_its_result_only_on_exit() -> None:
    with measure() as cost:
        assert cost == {}
    assert set(cost) == {"train_seconds", "peak_memory_mb", "added_memory_mb"}
