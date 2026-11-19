from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    """How the manager's rates enter training (decision 0071)."""

    # Weight of a night the manager priced, on night rows. Flat, like the
    # tune-up (0069): the rate is the manager's judgement, so the vacancy-based
    # weight no longer applies.
    manager_weight: float = 1.0
    # On booked rooms, a manager rate is a row of its own weighing this share
    # of the night's booked rooms, and at least 1 (decision 0076), so one
    # rate isn't drowned out by the night's sales.
    manager_share: float = 0.25


DEFAULT = FeedbackSettings()


@dataclass(frozen=True, slots=True)
class FeedbackEffect:
    rate: pd.Series  # the training target, manager's rates swapped in
    weights: np.ndarray  # sample weights, manager's nights set flat
    used: pd.DataFrame  # one row per manager rate that replaced a night's rate


USED_COLUMNS = ["feedback_id", "rate_replaced", "weight_factor", "training_rate"]


def apply_feedback(
    nights: pd.DataFrame,
    feedback: pd.DataFrame,
    rate: pd.Series,
    weights: np.ndarray,
    settings: FeedbackSettings = DEFAULT,
) -> FeedbackEffect:
    """Swaps the manager's rate in as the training rate of the nights they priced.

    The caller passes the latest version of each night's feedback that has a
    rate, given before or after the night. A night with no manager rate is left
    exactly as it was. This is the rule the daily tune-up follows too, so a full
    retrain and a tune-up learn from the manager the same way.

    Args:
        nights (pd.DataFrame): The nights being trained on, with columns
            stay_date and room_type.
        feedback (pd.DataFrame): Columns id, stay_date, room_type and rate; at
            most one row per room type per night. Rows with no rate are ignored.
        rate (pd.Series): The recorded rate of each night, indexed like nights.
        weights (np.ndarray): Each night's weight before feedback.
        settings (FeedbackSettings): How the manager's nights are weighted.

    Returns:
        FeedbackEffect: The new rate and weights, and which feedback was used.

    Raises:
        ValueError: If a night has more than one piece of feedback.
    """
    key = ["stay_date", "room_type"]
    feedback = feedback[feedback["rate"].notna()]
    if feedback.empty:
        return FeedbackEffect(rate, weights, pd.DataFrame(columns=USED_COLUMNS))
    if feedback.duplicated(key).any():
        raise ValueError("expected at most one piece of feedback per room type night")

    given = nights[key].merge(feedback[[*key, "id", "rate"]], on=key, how="left")
    has = given["id"].notna().to_numpy()
    manager = given["rate"].to_numpy(float)
    recorded = rate.to_numpy(float)
    old_weights = np.asarray(weights, dtype=float)

    training_rate = np.where(has, manager, recorded)
    new_weights = np.where(has, settings.manager_weight, old_weights)

    used = pd.DataFrame(
        {
            "feedback_id": given["id"].to_numpy()[has].astype(int),
            "rate_replaced": True,
            "weight_factor": settings.manager_weight / old_weights[has],
            "training_rate": training_rate[has],
        }
    )
    return FeedbackEffect(
        pd.Series(training_rate, index=rate.index, name=rate.name), new_weights, used
    )


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
