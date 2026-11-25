"""Why a night's rate is what it is: the model's terms, in words and euros."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

import pandas as pd

from foresight.services.ml.features import LEAD

# Terms worth naming in the explanation; smaller ones are summed as "other".
_MIN_FACTOR_EUR = 1.0
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]  # fmt: skip


@dataclass(frozen=True, slots=True)
class Factor:
    """One term's pull on the recommended rate."""

    detail: str  # the factor, e.g. "Saturday" or "event count 3"
    amount: Decimal  # contribution in currency; terms + baseline = the rate


@dataclass(frozen=True, slots=True)
class Explanation:
    summary: str
    baseline: Decimal  # the model's starting point before any term
    factors: list[Factor]


def explain_rate(
    intercept: float, contributions: pd.Series, row: pd.Series, pred: float
) -> Explanation:
    """Name every term worth at least €1; the rest is summed as "other".

    Amounts are rounded to cents, and "other" absorbs the rounding, so the
    baseline plus every amount always equals the recommended rate exactly.
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
    """Name a term by the night's value, e.g. "Saturday" or "booking 3 days ahead"."""
    # `row` is one night, so each column holds a single scalar; pandas' stubs
    # type indexing as possibly a Series, hence the cast.
    return " with ".join(
        _value(part, cast("float | int | str | None", row[part]))
        for part in term.split(" & ")
    )


def _value(feature: str, value: float | int | str | None) -> str:
    """One feature's value for this night, in words. Values are scalars:
    numbers for the calendar, events and days ahead, a name for the room
    type."""
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
    return f"{'+' if amount >= 0 else '-'}€{abs(amount):.2f}"


def money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def explanation_to_json(explanation: Explanation) -> dict[str, Any]:
    """The explanation as JSON: amounts as strings so cents stay exact."""
    return {
        "summary": explanation.summary,
        "baseline": str(explanation.baseline),
        "factors": [
            {"detail": f.detail, "amount": str(f.amount)} for f in explanation.factors
        ],
    }


def explanation_from_json(data: dict[str, Any]) -> Explanation:
    return Explanation(
        summary=data["summary"],
        baseline=Decimal(data["baseline"]),
        factors=[Factor(f["detail"], Decimal(f["amount"])) for f in data["factors"]],
    )
