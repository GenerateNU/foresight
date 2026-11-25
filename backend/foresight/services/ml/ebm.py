import io
from typing import Any, Self

import joblib
import numpy as np
import pandas as pd
from interpret.glassbox import ExplainableBoostingRegressor


class EBMModel:
    """An Explainable Boosting Machine, trained once on every row.

    Attributes:
        name (str): The algorithm's name, stored on each version.
        seed (int): The random seed.
        params (dict[str, Any]): Settings passed through to the EBM.
    """

    name: str = "ebm"

    def __init__(self, seed: int = 9, **params: Any) -> None:
        """Stores the settings; `fit` builds the EBM.

        Args:
            seed (int): The random seed.
            **params (Any): Settings passed through to the EBM.
        """
        self.seed = seed
        self.params = params
        self._model: ExplainableBoostingRegressor | None = None

    def fit(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        sample_weight: np.ndarray | None = None,
    ) -> Self:
        """Trains the model on every row.

        Args:
            x (pd.DataFrame): Training features.
            y (pd.Series): Training target (rate).
            sample_weight (np.ndarray | None): How much each row counts. None
                weights every row equally.

        Returns:
            Self: The trained model.

        Raises:
            ValueError: A sample weight isn't positive.
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

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        """Predicts the rate for each row.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One prediction per row of x.

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        return self._fitted().predict(x)

    def explain(self, x: pd.DataFrame) -> pd.DataFrame:
        """Splits each prediction into the contribution of every term.

        Each row's contributions plus `intercept` add up to its prediction.

        Args:
            x (pd.DataFrame): Features to explain.

        Returns:
            pd.DataFrame: One row per row of x, one column per term (features
                and pairwise interactions such as "day_of_week & month").

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        return _terms(self._fitted(), x)

    @property
    def intercept(self) -> float:
        """The prediction before any term contributes.

        Returns:
            float: The model's intercept.

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        return float(self._fitted().intercept_)

    @property
    def features(self) -> list[str]:
        """The input columns the model was trained on, in order.

        Returns:
            list[str]: Feature names.

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        return list(self._fitted().feature_names_in_)

    def to_bytes(self) -> bytes:
        """Serializes the trained model for storage.

        Returns:
            bytes: The trained model.

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        self._fitted()
        buffer = io.BytesIO()
        joblib.dump(self, buffer)
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        """Loads a model serialized by `to_bytes`.

        Only load bytes our own training wrote: unpickling can run code.

        Args:
            data (bytes): Output of `to_bytes`.

        Returns:
            Self: The trained model.

        Raises:
            TypeError: The bytes don't hold this class.
        """
        model = joblib.load(io.BytesIO(data))
        if not isinstance(model, cls):
            raise TypeError(f"Expected {cls.__name__}, got {type(model).__name__}")
        return model

    def _fitted(self) -> ExplainableBoostingRegressor:
        """Returns the trained EBM.

        Returns:
            ExplainableBoostingRegressor: The trained EBM.

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        if self._model is None:
            raise RuntimeError(f"{self.name} must be fit before predicting")
        return self._model


class TunedEBMModel(EBMModel):
    """A trained EBM left as it is, plus a small EBM that corrects it.

    The correction learns only the gap between the base's predictions and the
    rates it's fit on (`init_score`), so a prediction is the base's plus the
    correction's. It has no pairwise terms, so its terms are a subset of the
    base's and `explain` can add them up by name. It sees every input the
    base does; a few hundred rounds is enough, since on a handful of rows
    early stopping has almost nothing to judge by.

    Only the correction is serialized; the base is stored once, as its own
    version, and the tuned version points to it. After `from_bytes`, call
    `attach_base` with the base before predicting.

    Attributes:
        name (str): The algorithm's name, stored on each version.
        base (EBMModel | None): The model being corrected.
        CORRECTION_DEFAULTS (dict[str, Any]): The correction's EBM settings,
            before any passed in.
    """

    name: str = "ebm-tuned"
    CORRECTION_DEFAULTS: dict[str, Any] = {"interactions": 0, "max_rounds": 300}

    def __init__(self, base: EBMModel, **params: Any) -> None:
        """Wraps a trained base model; `fit` then trains the correction.

        Args:
            base (EBMModel): The trained model to correct. If it is itself a
                tuned model, its own base is used, so corrections never stack.
            **params (Any): Settings passed through to the correction EBM.

        Raises:
            RuntimeError: The base hasn't been fit.
        """
        if isinstance(base, TunedEBMModel):
            base = base._base()
        base._fitted()
        super().__init__(seed=base.seed, **params)
        self.base: EBMModel | None = None
        self.attach_base(base)

    def attach_base(self, base: EBMModel) -> Self:
        """Joins the correction to its base, e.g. after `from_bytes`.

        Args:
            base (EBMModel): The base version's trained model.

        Returns:
            Self: This model, ready to predict.

        Raises:
            TypeError: The base is itself a tune-up.
        """
        if isinstance(base, TunedEBMModel):
            raise TypeError("a tune-up's base must be a plain EBM, not a tune-up")
        self.base = base
        return self

    def __getstate__(self) -> dict[str, Any]:
        """Pickles the correction only; the base is stored as its own version.

        Returns:
            dict[str, Any]: The state, without the base.
        """
        return {**self.__dict__, "base": None}

    def fit(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        sample_weight: np.ndarray | None = None,
    ) -> Self:
        """Trains the correction on the gap between `y` and the base.

        Args:
            x (pd.DataFrame): Features of the nights to learn from.
            y (pd.Series): The rate each night should get.
            sample_weight (np.ndarray | None): How much each row counts. None
                weights every row equally.

        Returns:
            Self: The model with its correction trained.

        Raises:
            RuntimeError: No base is attached.
        """
        self._model = ExplainableBoostingRegressor(
            random_state=self.seed, **{**self.CORRECTION_DEFAULTS, **self.params}
        ).fit(x, y, sample_weight=sample_weight, init_score=self._base().predict(x))
        return self

    def correction(self, x: pd.DataFrame) -> np.ndarray:
        """Says how much the correction moves each prediction.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One amount per row of x, in rate units.

        Raises:
            RuntimeError: The model hasn't been fit.
        """
        return self._fitted().predict(x)

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        """Predicts the base's rate plus the correction, per row.

        Args:
            x (pd.DataFrame): Features to predict on.

        Returns:
            np.ndarray: One prediction per row of x.

        Raises:
            RuntimeError: The model hasn't been fit, or has no base.
        """
        return self._base().predict(x) + self.correction(x)

    def explain(self, x: pd.DataFrame) -> pd.DataFrame:
        """Gives the base's contributions with the correction's added.

        Args:
            x (pd.DataFrame): Features to explain.

        Returns:
            pd.DataFrame: One row per row of x, one column per base term.

        Raises:
            RuntimeError: The model hasn't been fit, or has no base.
        """
        base = self._base().explain(x)
        extra = _terms(self._fitted(), x)
        return base.add(extra, fill_value=0.0)[base.columns]

    @property
    def intercept(self) -> float:
        """The base's intercept plus the correction's.

        Returns:
            float: The combined intercept.

        Raises:
            RuntimeError: The model hasn't been fit, or has no base.
        """
        return self._base().intercept + float(self._fitted().intercept_)

    def _base(self) -> EBMModel:
        """Returns the attached base.

        Returns:
            EBMModel: The base.

        Raises:
            RuntimeError: No base is attached.
        """
        if self.base is None:
            raise RuntimeError(f"{self.name} needs attach_base before predicting")
        return self.base


def _terms(model: ExplainableBoostingRegressor, x: pd.DataFrame) -> pd.DataFrame:
    """Evaluates each of a trained EBM's terms on every row.

    Args:
        model (ExplainableBoostingRegressor): The trained EBM.
        x (pd.DataFrame): Features.

    Returns:
        pd.DataFrame: One row per row of x, one column per term.
    """
    return pd.DataFrame(model.eval_terms(x), columns=model.term_names_, index=x.index)
