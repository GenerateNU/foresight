from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

import pandas as pd

from foresight.services.ml.features import LEAD

_MIN_FACTOR_EUR = 1.0
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]  # fmt: skip


@dataclass(frozen=True, slots=True)
class Factor:
    """One term's pull on the recommended rate.

    Attributes:
        detail (str): The factor, e.g. "Saturday" or "event count 3".
        amount (Decimal): Its contribution in euros; every amount plus the
            baseline is the rate.
    """

    detail: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why a night's rate is what it is: the model's terms, in words and euros.

    Attributes:
        summary (str): One sentence.
        baseline (Decimal): The model's starting point before any term.
        factors (list[Factor]): Each term's pull, largest first.
    """

    summary: str
    baseline: Decimal
    factors: list[Factor]


def explain_rate(
    intercept: float, contributions: pd.Series, row: pd.Series, pred: float
) -> Explanation:
    """Names every term worth at least €1; the rest are summed as one.

    Amounts are rounded to cents, and the sum of the rest absorbs the
    rounding, so the baseline plus every amount equals the rate exactly.

    Args:
        intercept (float): The model's intercept.
        contributions (pd.Series): Each term's contribution for the night.
        row (pd.Series): The night's inputs.
        pred (float): The rate.

    Returns:
        Explanation: The explanation.
    """
    baseline = money(intercept)
    factors: list[Factor] = []
    for term, amount in contributions.sort_values(key=abs, ascending=False).items():
        if abs(amount) < _MIN_FACTOR_EUR:
            continue
        factors.append(Factor(detail=_describe(str(term), row), amount=money(amount)))
    other = money(pred) - baseline - sum((f.amount for f in factors), Decimal(0))
    if other:
        factors.append(Factor(detail="Smaller effects combined", amount=other))
    top = (
        f"{factors[0].detail}: {_signed(float(factors[0].amount))}"
        if factors
        else "no strong factors"
    )
    summary = f"€{pred:.0f} from a typical €{intercept:.0f}; biggest factor: {top}."
    return Explanation(summary, baseline, factors)


def _describe(term: str, row: pd.Series) -> str:
    """Names a term by the night's value, e.g. "Saturday with June".

    `row` is one night, so each column holds a scalar; pandas' stubs type
    indexing as possibly a Series, hence the cast.

    Args:
        term (str): A feature, or features joined by " & ".
        row (pd.Series): The night's inputs.

    Returns:
        str: The term in words.
    """
    return " with ".join(
        _value(part, cast("float | int | str | None", row[part]))
        for part in term.split(" & ")
    )


def _value(feature: str, value: float | int | str | None) -> str:
    """Puts one feature's value for a night into words.

    Args:
        feature (str): The feature.
        value (float | int | str | None): Its value; None or NaN if unknown.

    Returns:
        str: The value in words, e.g. "booking 3 days ahead".
    """
    if value is None or pd.isna(value):
        return f"{feature.replace('_', ' ')} unknown"
    if feature == LEAD:
        days = int(value)
        if days == 0:
            return "booking today"
        return f"booking {days} day{'' if days == 1 else 's'} ahead"
    if feature == "night_before_holiday":
        if int(value):
            return "the night before a public holiday"
        return "not the night before a public holiday"
    if feature == "is_public_holiday":
        return "a public holiday" if int(value) else "not a public holiday"
    if feature == "day_of_week":
        return _DAYS[int(value)]
    if feature == "month":
        return _MONTHS[int(value) - 1]
    return f"{feature.replace('_', ' ')} {value}"


def _signed(amount: float) -> str:
    """Formats an amount with its sign, e.g. "-€4.20".

    Args:
        amount (float): The amount.

    Returns:
        str: The amount.
    """
    return f"{'+' if amount >= 0 else '-'}€{abs(amount):.2f}"


def money(value: float) -> Decimal:
    """Rounds an amount to cents, halves up.

    Args:
        value (float): The amount.

    Returns:
        Decimal: The amount in cents.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def explanation_to_json(explanation: Explanation) -> dict[str, Any]:
    """Stores an explanation as JSON, amounts as strings so cents stay exact.

    Args:
        explanation (Explanation): The explanation.

    Returns:
        dict[str, Any]: The JSON.
    """
    return {
        "summary": explanation.summary,
        "baseline": str(explanation.baseline),
        "factors": [
            {"detail": f.detail, "amount": str(f.amount)} for f in explanation.factors
        ],
    }


def explanation_from_json(data: dict[str, Any]) -> Explanation:
    """Reads an explanation stored by `explanation_to_json`.

    Args:
        data (dict[str, Any]): The JSON.

    Returns:
        Explanation: The explanation.
    """
    return Explanation(
        summary=data["summary"],
        baseline=Decimal(data["baseline"]),
        factors=[Factor(f["detail"], Decimal(f["amount"])) for f in data["factors"]],
    )
