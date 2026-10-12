from abc import ABC, abstractmethod
from typing import Self

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


class Model(ABC):
    """Base class for all models. Subclasses implement fit and predict."""

    name: str = "model"

    def __init__(self, seed: int = 9, **params):
        """Stores the random seed and model-specific settings.

        Args:
            seed (int): Random seed for reproducible results.
            **params: Settings passed through to the underlying model.
        """
        self.seed = seed
        self.params = params
        self._model = None  # set by fit

    def _fitted(self):
        """Returns the underlying trained model.

        Returns:
            object: The model built by fit.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        if self._model is None:
            raise RuntimeError(f"{self.name} must be fit before predicting")
        return self._model

    @abstractmethod
    def fit(self, x: pd.DataFrame, y: pd.Series) -> Self:
        """Trains the model on the given data.

        Args:
            x (pd.DataFrame): Training features.
            y (pd.Series): Training target.

        Returns:
            Self: The trained model.
        """

    @abstractmethod
    def predict(self, x: pd.DataFrame) -> np.ndarray:
        """Predicts the target for each row.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One prediction per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
        """

    def predict_interval(
        self, x: pd.DataFrame, alpha: float = 0.05
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Predicts a value and a (1 - alpha) interval for each row.

        Args:
            x (pd.DataFrame): Features to predict on.
            alpha (float): Significance level; 0.05 gives a 95% interval.

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: Predictions, lower bounds,
                and upper bounds, one per row of x.

        Raises:
            NotImplementedError: If the model does not produce intervals.
        """
        raise NotImplementedError(f"{self.name} does not produce intervals")

    def evaluate(
        self, x: pd.DataFrame, y: pd.Series, alpha: float | None = None
    ) -> dict[str, float | None]:
        """Scores the model's predictions against the true values.

        Args:
            x (pd.DataFrame): Test features.
            y (pd.Series): True target values.
            alpha (float | None): Significance level for the interval coverage
                check. None uses the model's own default.

        Returns:
            dict[str, float | None]: mae, rmse, mape, r2, and coverage
                (share of y inside the (1 - alpha) interval. None if the model
                has no intervals).
        """
        y_true = np.asarray(y, dtype=float)
        y_pred = self.predict(x)

        nonzero = y_true != 0  # MAPE is undefined where the true value is 0
        mape = np.mean(np.abs((y_true - y_pred)[nonzero] / y_true[nonzero]))

        try:
            if alpha is None:
                _, lo, hi = self.predict_interval(x)
            else:
                _, lo, hi = self.predict_interval(x, alpha)
            coverage = float(np.mean((y_true >= lo) & (y_true <= hi)))
        except NotImplementedError:
            coverage = None

        return {
            "mae": mean_absolute_error(y_true, y_pred),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mape": float(mape),
            "r2": r2_score(y_true, y_pred),
            "coverage": coverage,
        }
