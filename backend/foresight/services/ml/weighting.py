import numpy as np
import pandas as pd


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


def combine_identical_rows(
    x: pd.DataFrame, y: pd.Series, weights: np.ndarray, stay_date: pd.Series
) -> tuple[pd.DataFrame, pd.Series, np.ndarray, np.ndarray]:
    """Merges rows the model can't tell apart: the same night and inputs.

    Booked rooms for one night that were booked on the same day have identical
    inputs. One row with their weighted mean rate and summed weight gives the
    same squared-error fit as one row each, in a fraction of the time
    (decision 0056). Nights are never merged with each other.

    Args:
        x (pd.DataFrame): The model's inputs, oldest first.
        y (pd.Series): The rate of each row.
        weights (np.ndarray): Each row's sample weight.
        stay_date (pd.Series): Each row's night, aligned with x.

    Returns:
        tuple: The merged rows' inputs, rates and weights, still oldest first,
            and for each input row the position of the merged row it went into.
    """
    keys = pd.concat(
        [pd.Series(stay_date.to_numpy(), index=x.index, name="_stay_date"), x],
        axis=1,
    )
    # sort=False numbers groups in order of first appearance, so merged rows
    # keep the input's time order.
    group = (
        keys.groupby(list(keys.columns), sort=False, dropna=False, observed=True)
        .ngroup()
        .to_numpy()
    )
    w = pd.Series(np.asarray(weights, dtype=float))
    total = w.groupby(group).sum()
    rate = (pd.Series(y.to_numpy(float)) * w).groupby(group).sum() / total
    first = pd.Series(np.arange(len(x))).groupby(group).first().to_numpy()
    return (
        x.iloc[first].reset_index(drop=True),
        rate.reset_index(drop=True).rename(y.name),
        total.to_numpy(),
        group,
    )
