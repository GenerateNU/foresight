"""Measuring a fit's time and memory (decision 0044). No DB."""

from __future__ import annotations

import time

import numpy as np

from foresight.services.ml.resources import SAMPLE_SECONDS, measure


def test_measure_sees_memory_the_block_allocates() -> None:
    with measure() as cost:
        block = np.ones(200 * 1024 * 1024 // 8)  # ~200 MB, touched so it's resident
        time.sleep(3 * SAMPLE_SECONDS)  # let the sampler see it
        del block

    assert cost["added_memory_mb"] >= 150
    assert cost["peak_memory_mb"] >= cost["added_memory_mb"]
    assert cost["train_seconds"] >= 3 * SAMPLE_SECONDS - 0.05


def test_measure_fills_its_result_only_on_exit() -> None:
    with measure() as cost:
        assert cost == {}
    assert set(cost) == {"train_seconds", "peak_memory_mb", "added_memory_mb"}
