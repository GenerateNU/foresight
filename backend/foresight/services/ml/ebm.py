import io

import joblib
import numpy as np
import pandas as pd
from interpret.glassbox import ExplainableBoostingRegressor


class EBMModel:
    """Explainable Boosting Machine, trained once on every row (decision 0085)."""

    name = "ebm"

    def __init__(self, seed: int = 9, **params):
        """Stores the random seed and settings passed through to the EBM."""
        self.seed = seed
        self.params = params
        self._model: ExplainableBoostingRegressor | None = None  # set by fit

    def _fitted(self) -> ExplainableBoostingRegressor:
        """The trained EBM. Raises RuntimeError before `fit`."""
        if self._model is None:
            raise RuntimeError(f"{self.name} must be fit before predicting")
        return self._model

    def fit(self, x, y, sample_weight=None):
        """Trains the model on every row.

        Args:
            x (pd.DataFrame): Training features.
            y (pd.Series): Training target (rate).
            sample_weight (np.ndarray | None): How much each row counts when
                training. None weights every row equally.

        Returns:
            EBMModel: The trained model.

        Raises:
            ValueError: If any sample weight is not positive.
        """
        weights = None
        if sample_weight is not None:
            weights = np.asarray(sample_weight, dtype=float)
            if not (weights > 0).all():
                raise ValueError(f"{self.name} needs every sample weight > 0")
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
            bytes: The trained model.

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


class TunedEBMModel(EBMModel):
    """A trained EBM left as it is, plus a small EBM that corrects it.

    The correction learns only the gap between the base's predictions and the
    rates it's fit on (`init_score`), so a prediction is the base's plus the
    correction's (decision 0069). It has no pairwise terms, so its terms are a
    subset of the base's and `explain` can add them up by name.

    Only the correction is serialized; the base is stored once, as its own
    version, and the tuned version points to it (decision 0078). After
    `from_bytes`, call `attach_base` with the base before predicting.
    """

    name = "ebm-tuned"
    # No pairwise terms, so `explain` can add terms up by name. A few hundred
    # rounds: on a handful of rows early stopping has almost nothing to judge
    # by, and the library's 25,000-round limit makes 5 rows take a minute.
    # It sees every input the base does (decision 0076); whether to keep `month`
    # out (0075) is an open question.
    CORRECTION_DEFAULTS = {"interactions": 0, "max_rounds": 300}

    def __init__(self, base: EBMModel, **params):
        """Wraps a trained base model; `fit` then trains the correction.

        Args:
            base (EBMModel): The trained model to correct. If it is itself a
                tuned model, its own base is used, so corrections never stack.
            **params: Settings passed through to the correction EBM.

        Raises:
            RuntimeError: If the base has not been fit.
        """
        if isinstance(base, TunedEBMModel):
            base = base._base()
        base._fitted()
        super().__init__(seed=base.seed, **params)
        self.base: EBMModel | None = None
        self.attach_base(base)

    def attach_base(self, base: EBMModel) -> "TunedEBMModel":
        """Joins the correction to its base, e.g. after `from_bytes`.

        Args:
            base (EBMModel): The base version's trained model.

        Returns:
            TunedEBMModel: This model, ready to predict.
        """
        if isinstance(base, TunedEBMModel):
            raise TypeError("a tune-up's base must be a plain EBM, not a tune-up")
        self.base = base
        return self

    def __getstate__(self):
        """Pickles the correction only; the base is stored as its own version."""
        return {**self.__dict__, "base": None}

    def _base(self) -> EBMModel:
        if self.base is None:
            raise RuntimeError(f"{self.name} needs attach_base before predicting")
        return self.base

    def fit(self, x, y, sample_weight=None):
        """Trains the correction on the gap between `y` and the base.

        Args:
            x (pd.DataFrame): Features of the nights to learn from.
            y (pd.Series): The rate each night should get.
            sample_weight (np.ndarray | None): How much each row counts. None
                weights every row equally.

        Returns:
            TunedEBMModel: The model with its correction trained.
        """
        self._model = ExplainableBoostingRegressor(
            random_state=self.seed, **{**self.CORRECTION_DEFAULTS, **self.params}
        ).fit(x, y, sample_weight=sample_weight, init_score=self._base().predict(x))
        return self

    def correction(self, x):
        """How much the correction moves each prediction.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One amount per row of x, in rate units.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return self._fitted().predict(x)

    def predict(self, x):
        """The base's prediction plus the correction, per row.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return self._base().predict(x) + self.correction(x)

    def explain(self, x):
        """The base's contributions with the correction's added, term by term.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        correction = self._fitted()
        base = self._base().explain(x)
        extra = pd.DataFrame(
            correction.eval_terms(x),
            columns=correction.term_names_,
            index=x.index,
        )
        return base.add(extra, fill_value=0.0)[base.columns]

    @property
    def intercept(self):
        """The base's intercept plus the correction's.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        return self._base().intercept + float(self._fitted().intercept_)
