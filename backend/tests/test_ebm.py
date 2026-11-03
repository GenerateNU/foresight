"""EBMModel.fit learns from every row, the newest included (decision 0045). No DB."""

from __future__ import annotations

import numpy as np
import pandas as pd

from foresight.services.ml.ebm import EBMModel


def _rows(n: int = 300, recent: int = 30) -> tuple[pd.DataFrame, pd.Series]:
    """Oldest first; `events` is only known on the newest `recent` rows, like
    event data that reaches back ~90 days, and adds 20 per event there."""
    rng = np.random.default_rng(0)
    x = pd.DataFrame(
        {
            "temp": rng.normal(size=n),
            "events": [np.nan] * (n - recent) + list(rng.integers(0, 5, recent)),
        }
    )
    y = 100 + 10 * x["temp"] + 20 * x["events"].fillna(0)
    return x, y


def test_learns_an_input_only_known_on_the_newest_rows() -> None:
    x, y = _rows()  # the 30 rows with events all fall in the 15% held out
    model = EBMModel(interactions=0, outer_bags=1).fit(x, y)

    quiet = pd.DataFrame({"temp": [0.0], "events": [0.0]})
    busy = pd.DataFrame({"temp": [0.0], "events": [4.0]})
    assert model.predict(busy)[0] - model.predict(quiet)[0] > 20


def test_scores_come_from_the_rows_held_out() -> None:
    x, y = _rows()
    model = EBMModel(interactions=0, outer_bags=1).fit(x, y)

    cut = int(len(x) * (1 - model.calibration_frac))
    assert model.holdout_pred is not None
    assert len(model.holdout_pred) == len(x) - cut
