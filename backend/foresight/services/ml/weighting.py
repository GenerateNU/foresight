import numpy as np
import pandas as pd

# Smallest weight a night can get. EBM rejects zero weights, and nights with
# many vacancies should still count a little.
MIN_WEIGHT = 0.05


def training_mask(rate: pd.Series) -> np.ndarray:
    """Marks which nights can be used for training.

    Free or staff rooms (rate of 0 or less) and nights with no listed rate say
    nothing about pricing, so they're left out entirely rather than weighted.

    Args:
        rate (pd.Series): Price listed each night.

    Returns:
        np.ndarray: True for each night to train on.
    """
    rate = rate.to_numpy(float)
    return ~np.isnan(rate) & (rate > 0)


def vacancy_factor(occupancy: pd.Series) -> np.ndarray:
    """Scores each night by how full it was.

    Vacancies on the day mean guests wouldn't pay the price, so emptier nights
    count less.

    Args:
        occupancy (pd.Series): Share of rooms sold each night, 0-1.

    Returns:
        np.ndarray: One factor per night, 0-1.
    """
    return occupancy.to_numpy(float)


def sample_weights(occupancy: pd.Series, min_weight: float = MIN_WEIGHT) -> np.ndarray:
    """Weights each night by how much its price should be trusted.

    New signals are added as their own factor function and multiplied in here.

    Args:
        occupancy (pd.Series): Share of rooms sold each night, 0-1.
        min_weight (float): Smallest weight any night gets; must be > 0.

    Returns:
        np.ndarray: One weight per night, all >= min_weight.

    Raises:
        ValueError: If min_weight is not positive, or any occupancy is missing.
    """
    if min_weight <= 0:
        raise ValueError("min_weight must be > 0")
    if occupancy.isna().any():
        raise ValueError("occupancy has missing values; can't weight those nights")
    return np.maximum(vacancy_factor(occupancy), min_weight)
