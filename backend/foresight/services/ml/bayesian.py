from scipy.stats import norm
from sklearn.linear_model import BayesianRidge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from foresight.services.ml.base import Model


class BayesianModel(Model):
    """Bayesian linear regression with standardized features."""

    name = "bayesian_ridge"

    def fit(self, x, y):
        """Trains the model on the given data.

        Args:
            x (pd.DataFrame): Training features.
            y (pd.Series): Training target.

        Returns:
            BayesianModel: The trained model.
        """
        self._model = make_pipeline(StandardScaler(), BayesianRidge(**self.params))
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

    def predict_interval(self, x, alpha=0.05):
        """Predicts a value and a (1 - alpha) interval for each row.

        Args:
            x (pd.DataFrame): Features to predict on.
            alpha (float): Significance level; 0.05 gives a 95% interval.

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: Predictions, lower bounds,
                and upper bounds, one per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        mean, std = self._fitted().predict(x, return_std=True)
        z = norm.ppf(1 - alpha / 2)
        return mean, mean - z * std, mean + z * std
