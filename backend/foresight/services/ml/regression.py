import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from foresight.services.ml.base import Model


class GBMModel(Model):
    "Gradient-boosted trees for per-booking dynamic pricing."

    name = "hist_gradient_boosting"

    def __init__(self, alpha=0.05, **params):
        super().__init__(**params)
        self.alpha = alpha

    def fit(self, x, y):
        """Trains point and quantile models on the given data.

        Args:
            x (pd.DataFrame): Training features (room_type should be a
                pandas categorical dtype).
            y (pd.Series): Training target (price).

        Returns:
            GBMModel: The trained model.
        """
        cat_cols = x.select_dtypes(include="category").columns.tolist()
        base_kwargs = {k: v for k, v in self.params.items() if k != "random_state"}
        random_state = self.params.get("random_state", 0)

        def make(loss, **extra):
            return HistGradientBoostingRegressor(
                loss=loss,
                categorical_features=cat_cols or None,
                random_state=random_state,
                **base_kwargs,
                **extra,
            )

        self._model = {
            "median": make("squared_error").fit(x, y),
            "lower": make("quantile", quantile=self.alpha / 2).fit(x, y),
            "upper": make("quantile", quantile=1 - self.alpha / 2).fit(x, y),
        }
        return self

    def predict(self, x):
        """Predicts the point price for each row.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One prediction per row of x.
        """
        return self._fitted()["median"].predict(x)

    def predict_interval(self, x, alpha=None):
        """Predicts a value and interval for each row.

        Args:
            x (pd.DataFrame): Features to predict on.
            alpha (float | None): Must match the alpha the model was
                fit with (its quantile heads are trained for one fixed
                alpha); pass None to use it implicitly.

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: Predictions, lower
                bounds, and upper bounds, one per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
            ValueError: If a different alpha than the one fit is requested.
        """
        if alpha is not None and not np.isclose(alpha, self.alpha):
            raise ValueError(
                f"{self.name} was fit with alpha={self.alpha}; its quantile "
                f"heads can't serve alpha={alpha}. Re-instantiate with "
                f"GBMModel(alpha={alpha}) and refit."
            )
        model = self._fitted()
        pred = model["median"].predict(x)
        lower = model["lower"].predict(x)
        upper = model["upper"].predict(x)
        # Lower/upper/median are three independently-fit models, so they can
        # occasionally cross or leave the median outside the band. Repair
        # that rather than let it silently violate lower <= pred <= upper.
        lower, upper = np.minimum(lower, upper), np.maximum(lower, upper)
        lower = np.minimum(lower, pred)
        upper = np.maximum(upper, pred)
        return pred, lower, upper
