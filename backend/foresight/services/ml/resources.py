"""How long a training fit takes and how much memory it uses (decision 0046).

Memory is this process's resident memory plus its children's: EBM fits in
parallel (joblib worker processes), so most of it is outside this process.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    from collections.abc import Iterator

# How often memory is sampled. A spike shorter than this can be missed; fits
# take seconds, so that's acceptable.
SAMPLE_SECONDS = 0.1
_MB = 1024 * 1024


def _rss() -> int:
    """Resident memory of this process and all its children, in bytes."""
    me = psutil.Process()
    total = me.memory_info().rss
    for child in me.children(recursive=True):
        with suppress(psutil.Error):  # exited between listing and reading
            total += child.memory_info().rss
    return total


@contextmanager
def measure() -> Iterator[dict[str, float]]:
    """Times the block and samples its memory; fills the yielded dict on exit.

    Keys, set once the block ends:
        train_seconds: wall-clock time of the block.
        peak_memory_mb: highest resident memory seen, this process and its
            children.
        added_memory_mb: that peak minus the memory at the start: what the
            block itself cost, since the API process already holds memory.
    """
    result: dict[str, float] = {}
    start_rss = peak = _rss()
    done = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not done.wait(SAMPLE_SECONDS):
            peak = max(peak, _rss())

    sampler = threading.Thread(target=sample, daemon=True)
    began = time.monotonic()
    sampler.start()
    try:
        yield result
    finally:
        seconds = time.monotonic() - began
        done.set()
        sampler.join()
        peak = max(peak, _rss())
        result["train_seconds"] = round(seconds, 1)
        result["peak_memory_mb"] = round(peak / _MB, 1)
        result["added_memory_mb"] = round((peak - start_rss) / _MB, 1)
