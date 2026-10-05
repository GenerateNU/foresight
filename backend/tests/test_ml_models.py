"""Each model predicting room rate on held-out, later nights."""

import numpy as np
import pandas as pd
import pytest

from foresight.services.ml.base import Model
from foresight.services.ml.bayesian import BayesianModel
from foresight.services.ml.neural_net import NNModel
from foresight.services.ml.regression import GBMModel
from foresight.services.ml.timeseries import TimeSeriesModel

MODELS = [BayesianModel, NNModel, GBMModel, TimeSeriesModel]


@pytest.fixture(scope="module", params=MODELS, ids=lambda m: m.name)
def fitted(request, price_split):
    """Each model, fit on the price training split."""
    x_train, _, y_train, _ = price_split
    return request.param().fit(x_train, y_train)


def test_predicts_one_price_per_row(fitted, price_split):
    """predict returns one positive price per test row."""
    _, x_test, _, _ = price_split
    pred = fitted.predict(x_test)
    assert pred.shape == (len(x_test),)
    assert (pred > 0).all()


@pytest.mark.parametrize("model_cls", MODELS, ids=lambda m: m.name)
def test_same_seed_gives_same_predictions(model_cls, price_split):
    """Two fits with the same seed give identical predictions."""
    x_train, x_test, y_train, _ = price_split
    first = model_cls(seed=3).fit(x_train, y_train).predict(x_test)
    second = model_cls(seed=3).fit(x_train, y_train).predict(x_test)
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize("model_cls", MODELS, ids=lambda m: m.name)
def test_predict_before_fit_raises(model_cls, price_split):
    """predict raises RuntimeError on an unfit model."""
    _, x_test, _, _ = price_split
    with pytest.raises(RuntimeError):
        model_cls().predict(x_test)


def test_bayesian_interval(price_split):
    """Bayesian intervals run, match predict, and contain the prediction."""
    x_train, x_test, y_train, y_test = price_split
    model = BayesianModel().fit(x_train, y_train)

    pred, lower, upper = model.predict_interval(x_test)
    np.testing.assert_array_equal(pred, model.predict(x_test))
    assert (lower < pred).all() and (pred < upper).all()
    assert 0.0 <= model.evaluate(x_test, y_test)["coverage"] <= 1.0


def test_nn_has_no_interval(price_split):
    """NN raises NotImplementedError for intervals; coverage is None."""
    x_train, x_test, y_train, y_test = price_split
    model = NNModel().fit(x_train, y_train)

    with pytest.raises(NotImplementedError):
        model.predict_interval(x_test)
    assert model.evaluate(x_test, y_test)["coverage"] is None


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
