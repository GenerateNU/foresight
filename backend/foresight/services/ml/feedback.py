from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    """How the manager's rates enter training (decisions 0071, 0076)."""

    # A manager rate is a booked-room row of its own weighing this share of
    # the night's booked rooms, and at least 1, so one rate isn't drowned out
    # by the night's sales.
    manager_share: float = 0.25


DEFAULT = FeedbackSettings()


def manager_row_weights(
    stay_date: pd.Series, rooms: pd.Series, settings: FeedbackSettings = DEFAULT
) -> np.ndarray:
    """The weight of each manager row on booked rooms (decision 0076).

    `manager_share` of the night's booked rooms, and at least 1, so a future
    night with no bookings yet still counts.

    Args:
        stay_date (pd.Series): The night of each manager row.
        rooms (pd.Series): Booked rooms per night, indexed by stay_date.
        settings (FeedbackSettings): How the manager's rates are weighted.

    Returns:
        np.ndarray: One weight per manager row.
    """
    booked = stay_date.map(rooms).fillna(0).to_numpy(float)
    return np.maximum(settings.manager_share * booked, 1.0)
