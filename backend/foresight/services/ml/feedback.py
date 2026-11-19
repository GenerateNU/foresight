from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    """How the manager's rates enter training (decision 0071)."""

    # Weight of a night the manager priced. Flat, like the tune-up (0069): the
    # rate is the manager's judgement, so the vacancy-based weight no longer
    # applies.
    manager_weight: float = 1.0


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
