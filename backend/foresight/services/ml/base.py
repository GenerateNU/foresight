from abc import ABC, abstractmethod
from typing import Any, Self

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
        self._model: Any = None  # set by fit

    def _fitted(self) -> Any:
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


def score(y_true: Any, y_pred: Any) -> dict[str, float]:
    """Scores predictions against the true values.

    Shared by models and the backtest's baselines, so both are measured alike.

    Args:
        y_true (array-like): True target values.
        y_pred (array-like): One prediction per true value.

    Returns:
        dict[str, float]: mae, rmse, mape, r2 and bias (mean of
            predicted - true; positive means it predicts too high).
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    nonzero = y_true != 0  # MAPE is undefined where the true value is 0
    mape = np.mean(np.abs((y_true - y_pred)[nonzero] / y_true[nonzero]))

    return {
        "mae": mean_absolute_error(y_true, y_pred),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mape": float(mape),
        "r2": r2_score(y_true, y_pred),
        "bias": float(np.mean(y_pred - y_true)),
    }
