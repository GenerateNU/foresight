"""Compares model performance on predicting room rate.

Run from backend/: uv run python scripts/compare_models.py
"""

import numpy as np
import pandas as pd
from generate_mock_data import write_csv

from foresight.services.ml.bayesian import BayesianModel
from foresight.services.ml.neural_net import NNModel
from foresight.services.ml.regression import GBMModel
from foresight.services.ml.timeseries import TimeSeriesModel

# Known only after the night, so never used to predict price.
POST_STAY_COLUMNS = ["rooms_sold", "occupancy", "room_revenue"]
MODELS = [BayesianModel, NNModel, GBMModel, TimeSeriesModel]
METRICS = ["mae", "rmse", "mape", "r2", "coverage"]
TEST_FRAC = 0.2
SEEDS = range(5)


def load_data() -> tuple[pd.DataFrame, pd.Series]:
    """Generates the mock data and splits it into features and target.

    Returns:
        tuple[pd.DataFrame, pd.Series]: Features and rate, sorted by stay_date.
    """
    df = pd.read_csv(write_csv(), parse_dates=["stay_date"])
    df = df.sort_values("stay_date", kind="stable").reset_index(drop=True)
    x = df.drop(columns=["rate", "stay_date", *POST_STAY_COLUMNS])
    x = pd.get_dummies(x, columns=["room_type", "condition"], dtype=float)
    return x, df["rate"]


def seed_runs(x_train, y_train, x_test, y_test) -> pd.DataFrame:
    """Scores each model on the holdout once per seed.

    Args:
        x_train (pd.DataFrame): Training features.
        y_train (pd.Series): Training target.
        x_test (pd.DataFrame): Holdout features.
        y_test (pd.Series): Holdout target.

    Returns:
        pd.DataFrame: One row per model per seed, with evaluate metrics.
    """
    rows = []
    for model_cls in MODELS:
        for seed in SEEDS:
            model = model_cls(seed=seed).fit(x_train, y_train)
            rows.append({"model": model.name, **model.evaluate(x_test, y_test)})
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    """Averages metrics per model.

    Args:
        results (pd.DataFrame): Output of seed_runs.

    Returns:
        pd.DataFrame: Mean and std of each metric, one row per model.
    """
    return results.groupby("model", sort=False)[METRICS].agg(["mean", "std"]).round(3)


def main():
    """Prints holdout results for each model."""
    x, y = load_data()
    cut = int(len(x) * (1 - TEST_FRAC))
    x_train, x_test, y_train, y_test = x[:cut], x[cut:], y[:cut], y[cut:]

    naive_mae = np.mean(np.abs(y_test - y_train.mean()))
    print(f"Baseline (always predict the average rate): MAE {naive_mae:.2f}\n")

    print(f"Holdout (last {TEST_FRAC:.0%} of nights, {len(SEEDS)} seeds)")
    print(summarize(seed_runs(x_train, y_train, x_test, y_test)).to_string())


if __name__ == "__main__":
    main()
