"""Nightly rate recommendations from the hotel's active pricing model.

Reads only what's already ingested; it never fetches. If data is missing for
the night, the model gets an empty value (it learned an effect for that)
rather than this call pulling the data in.

Returns domain dataclasses; the route maps them to `RecommendationResponse`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import pandas as pd

from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import (
    NO_EVENTS,
    NO_FLIGHTS,
    weather_for,
)
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.ebm import EBMModel
from foresight.services.ml.features import build_features

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City 
    from foresight.database.models.recommendation import RecommendationSnapshot


CURRENCY = "EUR"  # decision 0002
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

    detail: str  # the factor, e.g. "Saturday" or "18.3°C max"
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
class Recommendation:
    hotel_id: int
    stay_date: date
    room_type: str
    room_type_id: int
    recommended_rate: Decimal
    currency: str
    explanation: Explanation
    confidence_interval: ConfidenceInterval
    uncertainty: Decimal  # sub-model disagreement; high = review (decision 0006)
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
        room_type_id=room_type.id,
        recommended_rate=_money(pred),
        currency=CURRENCY,
        explanation=_explanation(model.intercept, contributions, row, pred),
        confidence_interval=ConfidenceInterval(
            _money(max(lower, 0.0)), _money(upper), round(1 - model.alpha, 2)
        ),
        uncertainty=_money(float(model.predict_uncertainty(x)[0])),
        model_id=stored.id,
        model_version=f"{stored.algorithm}-v{stored.version}",
        is_placeholder=False,
    )

async def snapshot_recommendations(
    session: AsyncSession,
    hotel_id: int,
    *,
    days: int = 30,
    room_type_id: int | None = None,
) -> list[RecommendationSnapshot]:
    """Recommend each night from today for `days` nights and save the ones
    that changed since their latest snapshot. Every room type unless one is
    given. Returns the snapshots saved."""
    hotel = await get_hotel(session, hotel_id)
    if room_type_id is None:
        room_type_ids = [r.id for r in await hotel_repo.list_room_types(session, hotel.id)]
    else:
        room_type_ids = [room_type_id]

    today = _today(hotel.city)
    saved: list[RecommendationSnapshot] = []
    for rt_id in room_type_ids:
        for offset in range(days):
            night = today + timedelta(days=offset)
            rec = await get_recommendation(session, hotel.id, night, room_type_id=rt_id)
            latest = await snapshot_repo.get_latest_snapshot(session, rt_id, stay_date=night)
            if _changed(latest, rec):
                saved.append(await _save(session, rec))
    return saved


async def get_snapshot(
    session: AsyncSession,
    hotel_id: int,
    stay_date: date,
    *,
    room_type_id: int | None = None,
) -> tuple[RecommendationSnapshot, RecommendationSnapshot | None]:
    """The latest and previous snapshot for one night of one room type.

    A future night with no snapshot gets one now. A past night is never
    created after the fact, so it raises NotFoundError instead.
    """
    hotel = await get_hotel(session, hotel_id)
    room_types = await hotel_repo.list_room_types(session, hotel.id)
    if room_type_id is None:
        room_type = room_types[0] if room_types else None
    else:
        room_type = next((r for r in room_types if r.id == room_type_id), None)
    if room_type is None:
        raise NotFoundError("Room type", room_type_id or "for hotel")

    latest = await snapshot_repo.get_latest_snapshot(
        session, room_type.id, stay_date=stay_date
    )
    if latest is None:
        if stay_date < _today(hotel.city):
            raise NotFoundError("Snapshot for night", stay_date)
        rec = await get_recommendation(
            session, hotel.id, stay_date, room_type_id=room_type.id
        )
        latest = await _save(session, rec)
    previous = await snapshot_repo.get_previous_snapshot(
        session, room_type.id, stay_date=stay_date
    )
    return latest, previous



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
        factors.append(Factor(detail=_describe(str(term), row), amount=_money(amount)))
    other = _money(pred) - baseline - sum((f.amount for f in factors), Decimal(0))
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
    """Name a term by the night's value, e.g. "Saturday" or "18.3°C max"."""
    # `row` is one night, so each column holds a single scalar; pandas' stubs
    # type indexing as possibly a Series, hence the cast.
    return " with ".join(
        _value(part, cast("float | int | str | None", row[part]))
        for part in term.split(" & ")
    )


def _value(feature: str, value: float | int | str | None) -> str:
    """One feature's value for this night, in words. Values are scalars:
    numbers for calendar and weather, a name for the room type."""
    if value is None or pd.isna(value):
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


def _signed(amount: float) -> str:
    return f"{'+' if amount >= 0 else '-'}€{abs(amount):.2f}"


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _changed(latest: RecommendationSnapshot | None, rec: Recommendation) -> bool:
    """Whether the new answer differs from the latest snapshot (model, rate or range)."""
    if latest is None:
        return True
    return (
        latest.rate != rec.recommended_rate
        or latest.model_id != rec.model_id
        or latest.interval_low != rec.confidence_interval.lower
        or latest.interval_high != rec.confidence_interval.upper
    )

def _factors(explanation: Explanation) -> dict[str, Any]:
    """The explanation as JSON: amounts as strings so cents stay exact."""
    return {
        "summary": explanation.summary,
        "baseline": str(explanation.baseline),
        "factors": [
            {"detail": f.detail, "amount": str(f.amount)}
            for f in explanation.factors
        ],
    }

async def _save(session: AsyncSession, rec: Recommendation) -> RecommendationSnapshot:
    """Save the robot's answer as a new snapshot."""
    return await snapshot_repo.create_recommendation_snapshot(
        session,
        hotel_id=rec.hotel_id,
        room_type_id=rec.room_type_id,
        stay_date=rec.stay_date,
        model_id=rec.model_id,
        model_version=rec.model_version,
        rate=rec.recommended_rate,
        interval_low=rec.confidence_interval.lower,
        interval_high=rec.confidence_interval.upper,
        uncertainty=rec.uncertainty,
        factors=_factors(rec.explanation),
    )
def _today(city: City) -> date:
    """Today where the city is: stay nights are local."""
    return datetime.now(ZoneInfo(city.timezone)).date()
