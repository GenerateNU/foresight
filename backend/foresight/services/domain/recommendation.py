"""Nightly rate recommendations from the hotel's active pricing model.

Reads only what's already ingested; it never fetches. If data is missing for
a night, the model gets an empty value (it learned an effect for that) rather
than this call pulling the data in.

Every night priced from today on is saved as a snapshot, and reused while its
inputs don't change (decision 0038):

1. Load each night's inputs: the model's input row, the events on the night
   and where its weather came from. Database reads only.
2. Fingerprint them with the active model's id.
3. A night whose fingerprint matches its latest snapshot returns that snapshot;
   the model doesn't run. The rest are scored together, in one batch, and each
   is saved as a new snapshot.

Past nights are never saved after the fact: one with a snapshot returns its
latest, as it was; one without is priced and returned unsaved.

Returns domain dataclasses; the route maps them to its response schemas.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

from foresight.database.enums import EventCategory
from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain import event as event_service
from foresight.services.domain.city import local_today
from foresight.services.domain.event import NightEvent
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

    from foresight.database.models.hotel import Hotel, RoomType
    from foresight.database.models.pricing_model import PricingModel
    from foresight.database.models.recommendation import RecommendationSnapshot


CURRENCY = "EUR"  # decision 0002
# One request scores its changed nights in one batch; this bounds the batch.
MAX_NIGHTS = 90
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
    """One night's rate, why, and what it was priced from."""

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
    events: list[NightEvent]  # the events on the night, largest first
    weather_source: str | None  # "recorded", "forecast", "typical week …"
    snapshot_id: int | None  # None for a past night priced but not saved
    priced_at: datetime  # when the model produced this rate


@dataclass(frozen=True, slots=True)
class _Night:
    """A night's inputs, before any model runs."""

    stay_date: date
    features: pd.DataFrame  # the model's input, one row
    events: list[NightEvent]
    weather_source: str
    inputs: dict[str, Any]  # what's stored with the snapshot
    inputs_hash: str


@dataclass(frozen=True, slots=True)
class _Scored:
    """What the model said about one night."""

    rate: Decimal
    interval: ConfidenceInterval
    uncertainty: Decimal
    explanation: Explanation


async def get_recommendations(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date,
    end: date,
    room_type_id: int | None = None,
) -> list[Recommendation]:
    """The recommended rate for each night in [start, end], oldest first.

    Reuses a night's latest snapshot while its inputs are unchanged; otherwise
    prices it and, from today on, saves a new snapshot.

    Raises:
        NotFoundError: Unknown hotel or room type, or no active model.
        InvalidRequestError: `end` before `start`, more than `MAX_NIGHTS`
            nights, or the model wasn't trained on the room type.
    """
    if end < start:
        raise InvalidRequestError("end must not be before start")
    if (end - start).days + 1 > MAX_NIGHTS:
        raise InvalidRequestError(f"at most {MAX_NIGHTS} nights at a time")

    hotel = await get_hotel(session, hotel_id)
    stored = await model_repo.get_active_pricing_model(session, hotel.id)
    if stored is None:
        raise NotFoundError("Active pricing model for hotel", hotel.id)
    room_type = await _room_type(session, hotel, room_type_id)
    trained_on = stored.training_summary.get("room_types", [])
    if trained_on and room_type.name not in trained_on:
        raise InvalidRequestError(
            f"model v{stored.version} wasn't trained on room type "
            f"{room_type.name!r}; train a new version"
        )

    nights = await _load_nights(session, hotel, room_type, stored, start, end)
    latest = await snapshot_repo.latest_snapshots(
        session, room_type.id, start=start, end=end
    )
    today = local_today(hotel.city)

    # A past night keeps the snapshot it has, whatever changed since.
    to_score = [
        n
        for n in nights
        if (snap := latest.get(n.stay_date)) is None
        or (n.stay_date >= today and snap.inputs_hash != n.inputs_hash)
    ]
    scored = await _score(session, stored, to_score, trained_on)

    out = []
    for night in nights:
        result = scored.get(night.stay_date)
        if result is None:
            out.append(_from_snapshot(latest[night.stay_date], hotel, room_type))
        elif night.stay_date >= today:
            snap = await _save(session, hotel, room_type, stored, night, result)
            out.append(_from_snapshot(snap, hotel, room_type))
        else:
            out.append(_unsaved(hotel, room_type, stored, night, result))
    return out


# --- inputs -----------------------------------------------------------------


async def _room_type(
    session: AsyncSession, hotel: Hotel, room_type_id: int | None
) -> RoomType:
    """The given room type, or the hotel's first. NotFoundError if neither."""
    room_types = await hotel_repo.list_room_types(session, hotel.id)
    if room_type_id is None:
        room_type = room_types[0] if room_types else None
    else:
        room_type = next((r for r in room_types if r.id == room_type_id), None)
    if room_type is None:
        raise NotFoundError("Room type", room_type_id or "for hotel")
    return room_type


async def _load_nights(
    session: AsyncSession,
    hotel: Hotel,
    room_type: RoomType,
    stored: PricingModel,
    start: date,
    end: date,
) -> list[_Night]:
    """Every night's inputs and their fingerprint, from the database only."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    events = await event_service.events_by_night(
        session, hotel.city_id, start=start, end=end
    )
    weather = await weather_for(session, hotel.city, days, fallback=True)
    frame = pd.DataFrame({"stay_date": days, "room_type": room_type.name})
    x = build_features(frame, NO_EVENTS, weather.frame, NO_FLIGHTS)

    nights = []
    for i, day in enumerate(days):
        features = x.iloc[[i]]  # a one-row frame keeps each column's dtype
        inputs = {
            "features": {k: _plain(v) for k, v in features.iloc[0].items()},
            "events": [_event_json(e) for e in events[day]],
            "weather_source": weather.sources[day],
        }
        nights.append(
            _Night(
                stay_date=day,
                features=features,
                events=events[day],
                weather_source=weather.sources[day],
                inputs=inputs,
                inputs_hash=_fingerprint(stored.id, inputs),
            )
        )
    return nights


def _fingerprint(model_id: int, inputs: dict[str, Any]) -> str:
    """SHA-256 of the model and everything it reads or shows for the night."""
    payload = json.dumps(
        {"model_id": model_id, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _plain(value: Any) -> Any:
    """A feature value as plain JSON: numpy scalars unwrapped, NaN as None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):  # numpy scalar
        return _plain(value.item())
    if isinstance(value, bool | int | float):
        return value
    return None if pd.isna(value) else str(value)


def _event_json(event: NightEvent) -> dict[str, Any]:
    return {**asdict(event), "category": event.category.value}


def _event_from_json(data: dict[str, Any]) -> NightEvent:
    return NightEvent(**{**data, "category": EventCategory(data["category"])})


# --- scoring ----------------------------------------------------------------


async def _score(
    session: AsyncSession,
    stored: PricingModel,
    nights: list[_Night],
    trained_on: list[str],
) -> dict[date, _Scored]:
    """Run the model once over every night given. Loads the model only if
    there is something to score."""
    if not nights:
        return {}
    artifact = await model_repo.get_artifact(session, stored.id)
    if artifact is None:
        raise NotFoundError("Pricing model", stored.id)
    model = EBMModel.from_bytes(artifact)

    x = pd.concat([n.features for n in nights], ignore_index=True)
    # A partial batch can't infer the trained category set; give it the model's.
    x["room_type"] = pd.Categorical(x["room_type"], categories=trained_on or None)
    pred, lower, upper = model.predict_interval(x)
    uncertainty = model.predict_uncertainty(x)
    contributions = model.explain(x)
    level = round(1 - model.alpha, 2)

    return {
        night.stay_date: _Scored(
            rate=_money(float(pred[i])),
            interval=ConfidenceInterval(
                _money(max(float(lower[i]), 0.0)), _money(float(upper[i])), level
            ),
            uncertainty=_money(float(uncertainty[i])),
            explanation=_explanation(
                model.intercept, contributions.iloc[i], x.iloc[i], float(pred[i])
            ),
        )
        for i, night in enumerate(nights)
    }


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


# --- snapshots --------------------------------------------------------------


async def _save(
    session: AsyncSession,
    hotel: Hotel,
    room_type: RoomType,
    stored: PricingModel,
    night: _Night,
    scored: _Scored,
) -> RecommendationSnapshot:
    """Store a freshly priced night as a new snapshot."""
    return await snapshot_repo.create_recommendation_snapshot(
        session,
        hotel_id=hotel.id,
        room_type_id=room_type.id,
        stay_date=night.stay_date,
        model_id=stored.id,
        model_version=_version(stored),
        rate=scored.rate,
        interval_low=scored.interval.lower,
        interval_high=scored.interval.upper,
        interval_level=scored.interval.level,
        uncertainty=scored.uncertainty,
        factors=_explanation_json(scored.explanation),
        inputs=night.inputs,
        inputs_hash=night.inputs_hash,
    )


def _from_snapshot(
    snap: RecommendationSnapshot, hotel: Hotel, room_type: RoomType
) -> Recommendation:
    """A stored snapshot, read back as a recommendation."""
    inputs = snap.inputs or {}  # empty on snapshots from before decision 0038
    return Recommendation(
        hotel_id=hotel.id,
        stay_date=snap.stay_date,
        room_type=room_type.name,
        room_type_id=room_type.id,
        recommended_rate=snap.rate,
        currency=CURRENCY,
        explanation=_explanation_from_json(snap.factors),
        confidence_interval=ConfidenceInterval(
            snap.interval_low, snap.interval_high, snap.interval_level
        ),
        uncertainty=snap.uncertainty,
        model_id=snap.model_id,
        model_version=snap.model_version,
        events=[_event_from_json(e) for e in inputs.get("events", [])],
        weather_source=inputs.get("weather_source"),
        snapshot_id=snap.id,
        priced_at=snap.created_at,
    )


def _unsaved(
    hotel: Hotel,
    room_type: RoomType,
    stored: PricingModel,
    night: _Night,
    scored: _Scored,
) -> Recommendation:
    """A past night priced now; returned but never stored."""
    return Recommendation(
        hotel_id=hotel.id,
        stay_date=night.stay_date,
        room_type=room_type.name,
        room_type_id=room_type.id,
        recommended_rate=scored.rate,
        currency=CURRENCY,
        explanation=scored.explanation,
        confidence_interval=scored.interval,
        uncertainty=scored.uncertainty,
        model_id=stored.id,
        model_version=_version(stored),
        events=night.events,
        weather_source=night.weather_source,
        snapshot_id=None,
        priced_at=datetime.now(UTC),
    )


def _version(stored: PricingModel) -> str:
    return f"{stored.algorithm}-v{stored.version}"


def _explanation_json(explanation: Explanation) -> dict[str, Any]:
    """The explanation as JSON: amounts as strings so cents stay exact."""
    return {
        "summary": explanation.summary,
        "baseline": str(explanation.baseline),
        "factors": [
            {"detail": f.detail, "amount": str(f.amount)} for f in explanation.factors
        ],
    }


def _explanation_from_json(data: dict[str, Any]) -> Explanation:
    return Explanation(
        summary=data["summary"],
        baseline=Decimal(data["baseline"]),
        factors=[Factor(f["detail"], Decimal(f["amount"])) for f in data["factors"]],
    )
