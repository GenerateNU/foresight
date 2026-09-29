from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from services.ml.base import Model

DEFAULTS = {
    "hidden_layer_sizes": (32, 16),
    "max_iter": 2000,
    "early_stopping": True,
}


class NNModel(Model):
    """Small feed-forward neural network with standardized features."""

    name = "mlp"

    def fit(self, x, y):
        """Trains the model on the given data.

        Args:
            x (pd.DataFrame): Training features.
            y (pd.Series): Training target.

        Returns:
            NNModel: The trained model.
        """
        params = {**DEFAULTS, **self.params}
        self._model = make_pipeline(
            StandardScaler(), MLPRegressor(random_state=self.seed, **params)
        )
        self._model.fit(x, y)
        return self

    def predict(self, x):
        """Predicts the target for each row.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One prediction per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return self._fitted().predict(x)
