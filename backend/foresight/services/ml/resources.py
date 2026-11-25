import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress

import psutil

SAMPLE_SECONDS = 0.1
_MB = 1024 * 1024


def _rss() -> int:
    """Measures the resident memory of this process and all its children.

    A child that exits between being listed and being read is skipped.

    Returns:
        int: Bytes in use.
    """
    me = psutil.Process()
    total = me.memory_info().rss
    for child in me.children(recursive=True):
        with suppress(psutil.Error):
            total += child.memory_info().rss
    return total


@contextmanager
def measure() -> Iterator[dict[str, float]]:
    """Times a training fit and samples its memory.

    Memory includes child processes, since the EBM fits in parallel joblib
    workers. It is sampled every `SAMPLE_SECONDS`, so a shorter spike can be
    missed; fits take seconds, so that's acceptable.

    Yields:
        dict[str, float]: Filled when the block ends, with `train_seconds`
            (wall-clock time), `peak_memory_mb` (highest memory seen) and
            `added_memory_mb` (that peak minus the memory at the start: what
            the block itself cost, since the API process already holds some).
    """
    result: dict[str, float] = {}
    start_rss = peak = _rss()
    done = threading.Event()

    def sample() -> None:
        """Raises `peak` to the memory in use, until the block ends."""
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
