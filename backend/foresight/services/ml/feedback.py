from dataclasses import dataclass

import numpy as np
import pandas as pd

from foresight.database.enums import FeedbackVerdict


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    """How far the manager's feedback may move training (decision 0044).

    Every number here caps what a few pieces of feedback can do to the model.
    """

    # Weight multiplier for a night the manager called about right: its rate is
    # confirmed, so the model leans on it more.
    about_right: float = 2.0
    # Weight multiplier for a night called too high or too low when there is no
    # usable manager rate: its rate is known to be off, but by how much isn't.
    wrong_no_rate: float = 0.5
    # Weight multiplier for a night whose rate was replaced: the replacement is
    # the manager's judgement, so the vacancy-based weight no longer applies.
    # Applied as a flat weight, not on top of it.
    replaced: float = 1.0
    # The manager's rate is kept within this share of the recorded rate, so one
    # outlandish number can't drag a night far from what guests paid.
    max_rate_change: float = 0.30


DEFAULT = FeedbackSettings()


@dataclass(frozen=True, slots=True)
class FeedbackEffect:
    rate: pd.Series  # the training target, manager's rates swapped in
    weights: np.ndarray  # sample weights, adjusted by feedback
    used: pd.DataFrame  # one row per piece of feedback that changed a night


USED_COLUMNS = ["feedback_id", "rate_replaced", "weight_factor", "training_rate"]


def apply_feedback(
    nights: pd.DataFrame,
    feedback: pd.DataFrame,
    rate: pd.Series,
    weights: np.ndarray,
    settings: FeedbackSettings = DEFAULT,
) -> FeedbackEffect:
    """Changes the training rate and weight of nights the manager gave feedback on.

    The caller passes only feedback given after the night, the latest version
    of each. A night with no feedback is left exactly as it was.

    - About right: the rate stands; the night's weight is multiplied up.
    - Too high or too low with a rate on the right side of the recorded one:
      the manager's rate replaces it (within `max_rate_change`), and the night
      gets a flat weight.
    - Too high or too low with no rate, or a rate that contradicts the verdict:
      the rate stands; the night's weight is multiplied down.

    Args:
        nights (pd.DataFrame): The nights being trained on, with columns
            stay_date and room_type.
        feedback (pd.DataFrame): Columns id, stay_date, room_type, verdict and
            rate (NaN for none); at most one row per room type per night.
        rate (pd.Series): The recorded rate of each night, indexed like nights.
        weights (np.ndarray): Each night's weight before feedback.
        settings (FeedbackSettings): How far feedback may move training.

    Returns:
        FeedbackEffect: The new rate and weights, and which feedback was used.

    Raises:
        ValueError: If a night has more than one piece of feedback.
    """
    if feedback.empty:
        return FeedbackEffect(rate, weights, pd.DataFrame(columns=USED_COLUMNS))
    key = ["stay_date", "room_type"]
    if feedback.duplicated(key).any():
        raise ValueError("expected at most one piece of feedback per room type night")

    given = nights[key].merge(
        feedback[[*key, "id", "verdict", "rate"]], on=key, how="left"
    )
    has = given["id"].notna().to_numpy()
    verdict = given["verdict"].to_numpy()
    manager = given["rate"].to_numpy(float)
    recorded = rate.to_numpy(float)

    right = has & (verdict == FeedbackVerdict.ABOUT_RIGHT)
    lower = has & (verdict == FeedbackVerdict.TOO_HIGH) & (manager < recorded)
    higher = has & (verdict == FeedbackVerdict.TOO_LOW) & (manager > recorded)
    replaced = lower | higher  # NaN compares false, so no-rate nights drop out
    wrong = has & ~right & ~replaced

    cap = settings.max_rate_change
    training_rate = np.where(
        replaced, np.clip(manager, recorded * (1 - cap), recorded * (1 + cap)), recorded
    )
    factor = np.ones(len(nights))
    factor[right] = settings.about_right
    factor[wrong] = settings.wrong_no_rate
    new_weights = np.asarray(weights, dtype=float) * factor
    new_weights[replaced] = settings.replaced
    factor[replaced] = settings.replaced / np.asarray(weights, dtype=float)[replaced]

    changed = right | replaced | wrong
    used = pd.DataFrame(
        {
            "feedback_id": given["id"].to_numpy()[changed].astype(int),
            "rate_replaced": replaced[changed],
            "weight_factor": factor[changed],
            "training_rate": training_rate[changed],
        }
    )
    return FeedbackEffect(
        pd.Series(training_rate, index=rate.index, name=rate.name), new_weights, used
    )
