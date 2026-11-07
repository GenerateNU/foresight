from __future__ import annotations

import pandas as pd

# Model input columns, in order. Training and serving both use this list.
# Calendar only for now: weather and events are disconnected from the model
# until notebook experiments show which inputs earn a place (decision 0051).
FEATURES = ["room_type", "day_of_week", "month"]

# FEATURES by kind, for choosing which inputs a backtest trains on. Every
# input is in exactly one group.
INPUT_GROUPS = {
    "calendar": ["room_type", "day_of_week", "month"],
}


def build_features(nights: pd.DataFrame) -> pd.DataFrame:
    """Builds the model's input columns, one row per room type per night.

    Used for training (past nights) and serving (the night being priced), so
    both see identical features.

    Args:
        nights (pd.DataFrame): One row per room type per night, with columns
            stay_date and room_type.

    Returns:
        pd.DataFrame: The FEATURES columns, in order, indexed like nights.
    """
    stay_date = pd.to_datetime(nights["stay_date"])
    features = pd.DataFrame(index=nights.index)
    features["room_type"] = nights["room_type"].astype("category")
    features["day_of_week"] = stay_date.dt.dayofweek.to_numpy()
    features["month"] = stay_date.dt.month.to_numpy()
    return features.reindex(columns=FEATURES)
