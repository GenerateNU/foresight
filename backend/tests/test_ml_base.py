"""The shared Model base: metrics and interval handling."""

import numpy as np
import pandas as pd
import pytest

from foresight.services.ml.base import Model


class FixedModel(Model):
    """Returns preset predictions and a +/-5 band, recording the alpha asked for."""

    name = "fixed"

    def __init__(self, pred):
        super().__init__()
        self.pred = np.asarray(pred, dtype=float)
        self.alpha_seen = "not called"

    def fit(self, x, y):
        """Does nothing; predictions are preset."""
        return self

    def predict(self, x):
        """Returns the preset predictions."""
        return self.pred

    def predict_interval(self, x, alpha="default"):
        """Returns the preset predictions with a +/-5 band; records alpha."""
        self.alpha_seen = alpha
        return self.pred, self.pred - 5, self.pred + 5


def test_evaluate_metrics():
    """evaluate computes each metric correctly on known values."""
    # Errors are -10, 10, -10, 0; the 0 true value is left out of MAPE.
    y = pd.Series([100.0, 200.0, 0.0, 400.0])
    model = FixedModel([110.0, 190.0, 10.0, 400.0])

    scores = model.evaluate(pd.DataFrame(index=y.index), y)

    assert scores["mae"] == pytest.approx(7.5)
    assert scores["rmse"] == pytest.approx(np.sqrt(75))
    assert scores["mape"] == pytest.approx((0.1 + 0.05 + 0.0) / 3)
    assert scores["r2"] == pytest.approx(1 - 300 / 87500)
    assert scores["coverage"] == pytest.approx(0.25)  # only the last row is within +/-5


def test_evaluate_passes_alpha_only_when_given():
    """evaluate passes alpha to predict_interval only when one is given."""
    y = pd.Series([1.0, 2.0])
    x = pd.DataFrame(index=y.index)
    model = FixedModel([1.0, 2.0])

    model.evaluate(x, y)
    assert model.alpha_seen == "default"  # model keeps its own alpha

    model.evaluate(x, y, alpha=0.2)
    assert model.alpha_seen == 0.2
