from __future__ import annotations

import pandas as pd

# Calendar inputs, in order. Weather and events are disconnected from the model
# until notebook experiments show which inputs earn a place (decision 0051).
FEATURES = ["room_type", "day_of_week", "month"]

LEAD = "lead_days"
ALL_FEATURES = [*FEATURES, LEAD]

# ALL_FEATURES by kind, for choosing which inputs a backtest trains on. Every
# input is in exactly one group.
INPUT_GROUPS = {
    "calendar": FEATURES,
    "lead_time": [LEAD],
}


def build_features(rows: pd.DataFrame) -> pd.DataFrame:
    """Builds the model's input columns, one row per night or per booked room.

    Used for training (past nights or bookings) and serving (the night being
    priced), so both see identical features.

    Args:
        rows (pd.DataFrame): Columns stay_date and room_type, and lead_days if
            the model reads it.

    Returns:
        pd.DataFrame: FEATURES, then lead_days if rows has it, indexed like rows.
    """
    stay_date = pd.to_datetime(rows["stay_date"])
    features = pd.DataFrame(index=rows.index)
    features["room_type"] = rows["room_type"].astype("category")
    features["day_of_week"] = stay_date.dt.dayofweek.to_numpy()
    features["month"] = stay_date.dt.month.to_numpy()
    if LEAD in rows:
        features[LEAD] = rows[LEAD].to_numpy()
    return features
