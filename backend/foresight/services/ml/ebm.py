import io

import joblib
import numpy as np
import pandas as pd
from interpret.glassbox import ExplainableBoostingRegressor

from foresight.services.ml.base import Model


class EBMModel(Model):
    """Explainable Boosting Machine with split-conformal prediction intervals."""

    name = "ebm"

    def __init__(self, alpha=0.2, calibration_frac=0.15, **params):
        """Stores the interval and calibration settings.

        Args:
            alpha (float): Default significance level; 0.2 gives an 80% interval.
            calibration_frac (float): Share of the most recent rows held out to
                calibrate the interval.
            **params: Seed and settings passed through to the EBM.
        """
        super().__init__(**params)
        self.alpha = alpha
        self.calibration_frac = calibration_frac
        self._residuals: np.ndarray | None = None  # set by fit
        self.holdout_pred: np.ndarray | None = None  # fit 1's predictions, set by fit

    def fit(self, x, y, sample_weight=None):
        """Trains the model and calibrates its prediction interval.

        Fits twice. First on all but the last `calibration_frac` of rows: its
        errors on those held-out rows set the interval width. Then on every
        row, and that fit is the model kept, so the newest rows are learned
        from too. Rows must be sorted by time so the held-out rows are the latest.

        Args:
            x (pd.DataFrame): Training features, sorted by time.
            y (pd.Series): Training target (rate).
            sample_weight (np.ndarray | None): How much each row counts when
                training. None weights every row equally.

        Returns:
            EBMModel: The trained model.

        Raises:
            ValueError: If there are too few rows to hold out a calibration set,
                or any sample weight is not positive.
        """
        cut = int(len(x) * (1 - self.calibration_frac))
        if cut < 1 or cut >= len(x):
            raise ValueError(
                f"{self.name} needs more rows to hold out a calibration set "
                f"(got {len(x)})"
            )

        weights = None
        if sample_weight is not None:
            weights = np.asarray(sample_weight, dtype=float)
            if not (weights > 0).all():
                raise ValueError(f"{self.name} needs every sample weight > 0")

        # Fit 1, oldest rows only: its errors on the newest rows, which it
        # hasn't seen, set the interval width and the reported scores.
        holdout = ExplainableBoostingRegressor(
            random_state=self.seed, **self.params
        ).fit(
            x.iloc[:cut],
            y.iloc[:cut],
            sample_weight=None if weights is None else weights[:cut],
        )

        self.holdout_pred = holdout.predict(x.iloc[cut:])
        self._residuals = np.abs(
            np.asarray(y.iloc[cut:], dtype=float) - self.holdout_pred
        )

        # Fit 2, every row: the model that's kept, so the newest nights (the
        # only ones with event data) are learned from too.
        self._model = ExplainableBoostingRegressor(
            random_state=self.seed, **self.params
        ).fit(x, y, sample_weight=weights)
        return self

    def predict(self, x):
        """Predicts the rate for each row.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One prediction per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return self._fitted().predict(x)

    def predict_interval(self, x, alpha=None):
        """Predicts a rate and a (1 - alpha) interval for each row.

        Args:
            x (pd.DataFrame): Features to predict on.
            alpha (float | None): Significance level. None uses the model's
                default.

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: Predictions, lower bounds,
                and upper bounds, one per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        pred = self.predict(x)
        margin = self.interval_margin(self.alpha if alpha is None else alpha)
        return pred, pred - margin, pred + margin

    def interval_margin(self, alpha):
        """Returns how far the interval extends either side of a prediction.

        Args:
            alpha (float): Significance level; 0.2 gives an 80% interval.

        Returns:
            float: The interval half-width, in rate units.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        self._fitted()
        residuals = self._residuals
        if residuals is None:
            raise RuntimeError(f"{self.name} must be fit before predicting")
        n = len(residuals)
        level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
        return float(np.quantile(residuals, level, method="higher"))

    def predict_uncertainty(self, x):
        """Measures how much the model's internal sub-models disagree per row.

        High values flag nights unlike the training data. This is not a range
        for the rate; use predict_interval for that.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One standard deviation per row of x, in rate units.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return self._fitted().predict_with_uncertainty(x)[:, 1]

    def explain(self, x):
        """Splits each prediction into the contribution of every term.

        Each row's contributions plus `intercept` add up to its prediction.

        Args:
            x (pd.DataFrame): Features to explain.

        Returns:
            pd.DataFrame: One row per row of x, one column per term (features
                and pairwise interactions such as "day_of_week & month").

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        model = self._fitted()
        return pd.DataFrame(
            model.eval_terms(x), columns=model.term_names_, index=x.index
        )

    @property
    def intercept(self):
        """The prediction before any term contributes.

        Returns:
            float: The model's intercept.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return float(self._fitted().intercept_)

    @property
    def features(self):
        """The input columns the model was trained on, in order.

        Returns:
            list[str]: Feature names.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return list(self._fitted().feature_names_in_)

    def to_bytes(self):
        """Serializes the trained model for storage.

        Returns:
            bytes: The model, including its calibration.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        self._fitted()
        buffer = io.BytesIO()
        joblib.dump(self, buffer)
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data):
        """Loads a model serialized by to_bytes.

        Only load bytes our own training wrote: unpickling can run code.

        Args:
            data (bytes): Output of to_bytes.

        Returns:
            EBMModel: The trained model.

        Raises:
            TypeError: If the bytes don't hold an EBMModel.
        """
        model = joblib.load(io.BytesIO(data))
        if not isinstance(model, cls):
            raise TypeError(f"Expected {cls.__name__}, got {type(model).__name__}")
        return model
