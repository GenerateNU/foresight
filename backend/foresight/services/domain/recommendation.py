"""Nightly rate recommendations from the hotel's active pricing model.

Reads only what's already ingested; it never fetches. If data is missing for
a night, the model gets an empty value (it learned an effect for that) rather
than this call pulling the data in.

Every price shown from today on is saved as a snapshot (decisions 0038, 0084):

1. Load each night's inputs: the model's input row, the events on the night
   and whether an events backfill covered it. Database reads only. Days booked
   ahead are among them: the rate is what the night would sell for if booked
   today, so a future night's inputs change daily (decision 0056).
2. A night whose latest snapshot has the same model and inputs returns that
   snapshot: the same model on the same inputs gives the same price. The rest
   are scored together, in one batch, and each is saved as a new snapshot.

Past nights are never saved after the fact: one with a snapshot returns its
latest, as it was; one without is priced and returned unsaved.

Returns domain dataclasses; the route maps them to its response schemas.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

from foresight.database.enums import EventCategory
from foresight.repository import feedback as feedback_repo
from foresight.repository import hotel as hotel_repo
from foresight.repository import pricing_model as model_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain import event as event_service
from foresight.services.domain.city import local_today
from foresight.services.domain.event import NightEvent
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.model_inputs import events_for, hotel_location
from foresight.services.domain.pricing_model import load_model
from foresight.services.errors import InvalidRequestError, NotFoundError
from foresight.services.ml.features import LEAD, build_features

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel, RoomType
    from foresight.database.models.pricing_model import PricingModel
    from foresight.database.models.recommendation import RecommendationSnapshot


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

    detail: str  # the factor, e.g. "Saturday" or "event count 3"
    amount: Decimal  # contribution in currency; terms + baseline = the rate


@dataclass(frozen=True, slots=True)
class Explanation:
    summary: str
    baseline: Decimal  # the model's starting point before any term
    factors: list[Factor]


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One night's rate, why, and what it was priced from."""

    hotel_id: int
    stay_date: date
    room_type: str
    room_type_id: int
    lead_days: int | None  # days from today it was priced at; None on old snapshots
    recommended_rate: Decimal
    explanation: Explanation
    model_id: int
    events: list[NightEvent]  # the events on the night, largest first
    events_source: str | None  # "fetched" or "missing"; None on older snapshots
    snapshot_id: int | None  # None for a past night priced but not saved
    priced_at: datetime  # when the model produced this rate
    # The rate the manager set for the night; None if they haven't. Read live,
    # never stored in a snapshot, so it never triggers a new one (decision 0071).
    manager_rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _Night:
    """A night's inputs, before any model runs."""

    stay_date: date
    features: pd.DataFrame  # the model's input, one row
    events: list[NightEvent]
    events_source: str  # "fetched" or "missing"
    inputs: dict[str, Any]  # what's stored with the snapshot


@dataclass(frozen=True, slots=True)
class _Scored:
    """What the model said about one night."""

    rate: Decimal
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
        NotFoundError: Unknown hotel, or no active model.
        InvalidRequestError: `end` before `start`, more than `MAX_NIGHTS`
            nights, or a room type the model doesn't price.
    """
    if end < start:
        raise InvalidRequestError("end must not be before start")
    if (end - start).days + 1 > MAX_NIGHTS:
        raise InvalidRequestError(f"at most {MAX_NIGHTS} nights at a time")

    hotel = await get_hotel(session, hotel_id)
    stored = await model_repo.get_active_pricing_model(session, hotel.id)
    if stored is None:
        raise NotFoundError("Active pricing model for hotel", hotel.id)
    room_type = await _room_type(session, stored, room_type_id)

    today = local_today(hotel.city)
    nights = await _load_nights(session, hotel, room_type, stored, today, start, end)
    latest = await snapshot_repo.latest_snapshots(
        session, room_type.id, start=start, end=end
    )

    # A past night keeps the snapshot it has, whatever changed since. A future
    # night is priced again unless its latest snapshot is the same model on the
    # same inputs, which would give the same price.
    to_score = [
        n
        for n in nights
        if (snap := latest.get(n.stay_date)) is None
        or (
            n.stay_date >= today
            and (snap.model_id != stored.id or snap.inputs != n.inputs)
        )
    ]
    scored = await _score(session, stored, to_score)

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
    rates = await feedback_repo.manager_rates(
        session, room_type.id, start=start, end=end
    )
    return [replace(r, manager_rate=rates.get(r.stay_date)) for r in out]


# --- inputs -----------------------------------------------------------------


async def _room_type(
    session: AsyncSession, stored: PricingModel, room_type_id: int | None
) -> RoomType:
    """The room type the active version prices (decision 0079).

    Raises:
        InvalidRequestError: The version predates 0079 and prices no room
            type, or `room_type_id` is another room type.
    """
    if stored.room_type_id is None:
        raise InvalidRequestError(
            f"model v{stored.version} predates the main room type; train a new version"
        )
    if room_type_id is not None and room_type_id != stored.room_type_id:
        raise InvalidRequestError(
            f"model v{stored.version} prices only room type {stored.room_type_id}"
        )
    room_type = await hotel_repo.get_room_type(session, stored.room_type_id)
    assert room_type is not None  # the foreign key cascades
    return room_type


async def _load_nights(
    session: AsyncSession,
    hotel: Hotel,
    room_type: RoomType,
    stored: PricingModel,
    today: date,
    start: date,
    end: date,
) -> list[_Night]:
    """Every night's inputs, from the database only.

    Builds every input, then keeps the ones this version trained on, so an
    older version gets exactly its own columns. Days booked ahead are counted
    from today; a past night gets 0.
    """
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    events = await event_service.events_by_night(
        session, hotel.city_id, start=start, end=end
    )
    city_events = await events_for(session, hotel.city, days)
    frame = pd.DataFrame({"stay_date": days})
    x = build_features(
        frame,
        city_events.frame,
        events_fetched=city_events.fetched,
        events_impacts=city_events.impacts,
        hotel_location=hotel_location(hotel),
        booked_on=today,
    )[stored.features]

    nights = []
    for i, day in enumerate(days):
        features = x.iloc[[i]]  # a one-row frame keeps each column's dtype
        events_source = "fetched" if day in city_events.fetched else "missing"
        inputs = {
            "features": {k: _plain(v) for k, v in features.iloc[0].items()},
            "events": [_event_json(e) for e in events[day]],
            "events_source": events_source,
        }
        nights.append(
            _Night(
                stay_date=day,
                features=features,
                events=events[day],
                events_source=events_source,
                inputs=inputs,
            )
        )
    return nights


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
) -> dict[date, _Scored]:
    """Run the model once over every night given. Loads the model only if
    there is something to score."""
    if not nights:
        return {}
    model = await load_model(session, stored)

    x = pd.concat([n.features for n in nights], ignore_index=True)
    pred = model.predict(x)
    contributions = model.explain(x)

    return {
        night.stay_date: _Scored(
            rate=_money(float(pred[i])),
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
        rate=scored.rate,
        factors=_explanation_json(scored.explanation),
        inputs=night.inputs,
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
        lead_days=_lead_days(inputs),
        recommended_rate=snap.rate,
        explanation=_explanation_from_json(snap.factors),
        model_id=snap.model_id,
        events=[_event_from_json(e) for e in inputs.get("events", [])],
        events_source=inputs.get("events_source"),
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
        lead_days=_lead_days(night.inputs),
        recommended_rate=scored.rate,
        explanation=scored.explanation,
        model_id=stored.id,
        events=night.events,
        events_source=night.events_source,
        snapshot_id=None,
        priced_at=datetime.now(UTC),
    )


def _lead_days(inputs: dict[str, Any]) -> int | None:
    """The days ahead a night was priced at, from its stored inputs; None on
    snapshots from versions that didn't read them."""
    value = inputs.get("features", {}).get(LEAD)
    return None if value is None else int(value)


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
