"""Nightly rate recommendations from the hotel's active pricing model.

Reads only what's already ingested; it never fetches. If a signal is missing
for the night, the model gets an empty value (it learned an effect for that)
and the response says so, rather than this call pulling the data in.

Returns domain dataclasses; the route maps them to `RecommendationResponse`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal

import pandas as pd

from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import (
    NO_EVENTS,
    NO_FLIGHTS,
    WEATHER_COLUMNS,
    weather_for,
)
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import build_features

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

CURRENCY = "EUR"  # decision 0002
# Terms worth naming in the explanation; smaller ones are summed as "other".
_MIN_FACTOR_EUR = 1.0
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]  # fmt: skip
# Which signal each model term belongs to; interactions take their first part.
_SIGNAL = {
    "room_type": "room type",
    "day_of_week": "calendar",
    "month": "calendar",
    "is_public_holiday": "calendar",
    "is_school_holiday": "calendar",
    "temp_max_c": "weather",
    "precip_mm": "weather",
    "wind_kph": "weather",
    "event_count": "events",
    "event_attendance": "events",
    "event_rank_max": "events",
    "flight_count": "flights",
    "avg_fare_eur": "flights",
}


@dataclass(frozen=True, slots=True)
class Factor:
    """One term's pull on the recommended rate."""

    signal: str  # "calendar", "weather", "room type", "events", "flights"
    direction: Literal["up", "down", "neutral"]
    detail: str
    amount: Decimal  # contribution in currency; terms + baseline = the rate


@dataclass(frozen=True, slots=True)
class Explanation:
    summary: str
    baseline: Decimal  # the model's starting point before any term
    factors: list[Factor]


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: Decimal
    upper: Decimal
    level: float  # coverage, e.g. 0.8


@dataclass(frozen=True, slots=True)
class SignalUsed:
    """What the model saw for one signal on this night."""

    signal: str
    source: str  # "recorded", "forecast", "typical week 43 (4 years)", "missing"
    values: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class Recommendation:
    hotel_id: int
    stay_date: date
    room_type: str
    recommended_rate: Decimal
    currency: str
    explanation: Explanation
    confidence_interval: ConfidenceInterval
    uncertainty: Decimal  # sub-model disagreement; high = review (decision 0006)
    signals: list[SignalUsed]
    model_id: int
    model_version: str
    is_placeholder: bool  # kept for clients written against the placeholder


async def get_recommendation(
    session: AsyncSession,
    hotel_id: int,
    stay_date: date,
    *,
    room_type_id: int | None = None,
) -> Recommendation:
    """The recommended rate for one night of one room type.

    Raises:
        NotFoundError: Unknown hotel or room type, or no active model.
        InvalidRequestError: The room type belongs to another hotel or the
            model wasn't trained on it.
    """
    hotel = await get_hotel(session, hotel_id)
    stored = await model_repo.get_active_pricing_model(session, hotel.id)
    if stored is None:
        raise NotFoundError("Active pricing model for hotel", hotel.id)

    room_types = await hotel_repo.list_room_types(session, hotel.id)
    if room_type_id is None:
        room_type = room_types[0] if room_types else None
    else:
        room_type = next((r for r in room_types if r.id == room_type_id), None)
    if room_type is None:
        raise NotFoundError("Room type", room_type_id or "for hotel")
    trained_on = stored.training_summary.get("room_types", [])
    if trained_on and room_type.name not in trained_on:
        raise InvalidRequestError(
            f"model v{stored.version} wasn't trained on room type "
            f"{room_type.name!r}; train a new version"
        )

    model = EBMModel.from_bytes(stored.artifact)
    weather = await weather_for(session, hotel.city, [stay_date], fallback=True)
    nights = pd.DataFrame({"stay_date": [stay_date], "room_type": [room_type.name]})
    x = build_features(nights, NO_EVENTS, weather.frame, NO_FLIGHTS)
    # A single row can't infer the trained category set; give it the model's.
    x["room_type"] = pd.Categorical(x["room_type"], categories=trained_on or None)

    pred, lower, upper = (float(v[0]) for v in model.predict_interval(x))
    contributions = model.explain(x).iloc[0]
    row = x.iloc[0]

    return Recommendation(
        hotel_id=hotel.id,
        stay_date=stay_date,
        room_type=room_type.name,
        recommended_rate=_money(pred),
        currency=CURRENCY,
        explanation=_explanation(model.intercept, contributions, row, pred),
        confidence_interval=ConfidenceInterval(
            _money(max(lower, 0.0)), _money(upper), round(1 - model.alpha, 2)
        ),
        uncertainty=_money(float(model.predict_uncertainty(x)[0])),
        signals=_signals(weather.sources[stay_date], row),
        model_id=stored.id,
        model_version=f"{stored.algorithm}-v{stored.version}",
        is_placeholder=False,
    )


def _explanation(
    intercept: float, contributions: pd.Series, row: pd.Series, pred: float
) -> Explanation:
    """Name every term worth at least €1; the rest is summed as "other".

    Amounts are rounded to cents, and "other" absorbs the rounding, so the
    baseline plus every amount always equals the recommended rate exactly.
    """
    baseline = _money(intercept)
    factors: list[Factor] = []
    for term, amount in contributions.sort_values(key=abs, ascending=False).items():
        if abs(amount) < _MIN_FACTOR_EUR:
            continue
        factors.append(
            Factor(
                signal=_SIGNAL.get(term.split(" & ")[0], "other"),
                direction="up" if amount > 0 else "down",
                detail=f"{_describe(term, row)}: {_signed(amount)}",
                amount=_money(amount),
            )
        )
    other = _money(pred) - baseline - sum((f.amount for f in factors), Decimal(0))
    if other:
        factors.append(
            Factor(
                "other",
                "neutral",
                f"Smaller effects combined: {_signed(float(other))}",
                other,
            )
        )
    top = factors[0].detail if factors else "no strong factors"
    summary = f"€{pred:.0f} from a typical €{intercept:.0f}; biggest factor: {top}."
    return Explanation(summary, baseline, factors)


def _describe(term: str, row: pd.Series) -> str:
    """Name a term by the night's value, e.g. "Saturday" or "18.3°C max"."""
    return " with ".join(_value(part, row[part]) for part in term.split(" & "))


def _value(feature: str, value: object) -> str:
    if pd.isna(value):
        return f"{feature.replace('_', ' ')} unknown"
    if feature == "day_of_week":
        return _DAYS[int(value)]
    if feature == "month":
        return _MONTHS[int(value) - 1]
    if feature == "temp_max_c":
        return f"{float(value):.1f}°C max"
    if feature == "precip_mm":
        return f"{float(value):.1f} mm rain"
    if feature == "wind_kph":
        return f"{float(value):.0f} km/h wind"
    if feature == "room_type":
        return f"{value} room"
    return f"{feature.replace('_', ' ')} {value}"


def _signals(weather_source: str, row: pd.Series) -> list[SignalUsed]:
    weather = {c: None if pd.isna(row[c]) else float(row[c]) for c in WEATHER_COLUMNS}
    return [
        SignalUsed("weather", weather_source, weather),
        SignalUsed("events", "not used yet", {}),
        SignalUsed("flights", "not used yet", {}),
    ]


def _signed(amount: float) -> str:
    return f"{'+' if amount >= 0 else '-'}€{abs(amount):.2f}"


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
