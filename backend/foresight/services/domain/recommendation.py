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
from typing import TYPE_CHECKING, Any

import pandas as pd

from foresight.database.enums import EventCategory
from foresight.repository import hotel as hotel_repo
from foresight.repository import recommendation as recommendation_repo
from foresight.services.domain import event as event_service
from foresight.services.domain.city import local_today
from foresight.services.domain.event import NightEvent
from foresight.services.domain.explanation import (
    Explanation,
    explain_rate,
    explanation_from_json,
    explanation_to_json,
    money,
)
from foresight.services.domain.feedback import current_feedback
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.inputs import build_inputs
from foresight.services.domain.model import get_active_model, load_model
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.features import LEAD

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel, RoomType
    from foresight.database.models.model import PricingModel
    from foresight.database.models.recommendation import RecommendationSnapshot


# One request scores its changed nights in one batch; this bounds the batch.
MAX_NIGHTS = 90


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
    # never version_row in a snapshot, so it never triggers a new one (decision 0071).
    manager_rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _Night:
    """A night's inputs, before any model runs."""

    stay_date: date
    features: pd.DataFrame  # the model's input, one row
    events: list[NightEvent]
    events_source: str  # "fetched" or "missing"
    inputs: dict[str, Any]  # what's version_row with the snapshot


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
    version_row = await get_active_model(session, hotel.id)
    room_type = await _room_type(session, version_row, room_type_id)
    today = local_today(hotel.city)
    nights = await _load_nights(session, hotel, version_row, today, start, end)
    latest = await recommendation_repo.latest_snapshots(
        session, room_type.id, start=start, end=end
    )
    scored = await _score(
        session, version_row, _to_price(nights, latest, version_row, today)
    )

    out = []
    for night in nights:
        result = scored.get(night.stay_date)
        if result is None:
            out.append(_from_snapshot(latest[night.stay_date], hotel, room_type))
        elif night.stay_date >= today:
            snap = await _save(session, hotel, room_type, version_row, night, result)
            out.append(_from_snapshot(snap, hotel, room_type))
        else:
            out.append(_unsaved(hotel, room_type, version_row, night, result))
    feedback = await current_feedback(session, room_type.id, start=start, end=end)
    rates = feedback.manager_rates
    return [replace(r, manager_rate=rates.get(r.stay_date)) for r in out]


def _to_price(
    nights: list[_Night],
    latest: dict[date, RecommendationSnapshot],
    version_row: PricingModel,
    today: date,
) -> list[_Night]:
    """Picks the nights to price now.

    A night with no snapshot is priced. A past night keeps the snapshot it
    has. A future night is priced again unless its latest snapshot has the
    same model and inputs, which would give the same price.

    Args:
        nights (list[_Night]): Every night requested, with its inputs.
        latest (dict[date, RecommendationSnapshot]): Each night's latest
            snapshot, where it has one.
        version_row (PricingModel): The active version.
        today (date): Today in the hotel's city.

    Returns:
        list[_Night]: The nights to price.
    """
    return [
        n
        for n in nights
        if (snap := latest.get(n.stay_date)) is None
        or (
            n.stay_date >= today
            and (snap.model_id != version_row.id or snap.inputs != n.inputs)
        )
    ]


# --- inputs -----------------------------------------------------------------


async def _room_type(
    session: AsyncSession, version_row: PricingModel, room_type_id: int | None
) -> RoomType:
    """The room type the active version prices (decision 0079).

    Raises:
        InvalidRequestError: The version predates 0079 and prices no room
            type, or `room_type_id` is another room type.
    """
    if version_row.room_type_id is None:
        raise InvalidRequestError(
            f"model v{version_row.version} predates the main room type; "
            "train a new version"
        )
    if room_type_id is not None and room_type_id != version_row.room_type_id:
        raise InvalidRequestError(
            f"model v{version_row.version} prices only room type "
            f"{version_row.room_type_id}"
        )
    room_type = await hotel_repo.get_room_type(session, version_row.room_type_id)
    assert room_type is not None  # the foreign key cascades
    return room_type


async def _load_nights(
    session: AsyncSession,
    hotel: Hotel,
    version_row: PricingModel,
    today: date,
    start: date,
    end: date,
) -> list[_Night]:
    """Builds every night's inputs, from the database only.

    Keeps only the inputs this version trained on. Days booked ahead are
    counted from today; a past night gets 0.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel, with its city loaded.
        version_row (PricingModel): The active version.
        today (date): Today in the hotel's city.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        list[_Night]: One per night, oldest first.
    """
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    events = await event_service.events_by_night(
        session, hotel.city_id, start=start, end=end
    )
    inputs = await build_inputs(
        session, hotel, pd.DataFrame({"stay_date": days}), booked_on=today
    )
    x = inputs.x[version_row.features]
    nights = []
    for i, day in enumerate(days):
        features = x.iloc[[i]]
        events_source = "fetched" if day in inputs.events_fetched else "missing"
        nights.append(
            _Night(
                stay_date=day,
                features=features,
                events=events[day],
                events_source=events_source,
                inputs={
                    "features": {k: _plain(v) for k, v in features.iloc[0].items()},
                    "events": [_event_json(e) for e in events[day]],
                    "events_source": events_source,
                },
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
    version_row: PricingModel,
    nights: list[_Night],
) -> dict[date, _Scored]:
    """Run the model once over every night given. Loads the model only if
    there is something to score."""
    if not nights:
        return {}
    model = await load_model(session, version_row)

    x = pd.concat([n.features for n in nights], ignore_index=True)
    pred = model.predict(x)
    contributions = model.explain(x)

    return {
        night.stay_date: _Scored(
            rate=money(float(pred[i])),
            explanation=explain_rate(
                model.intercept, contributions.iloc[i], x.iloc[i], float(pred[i])
            ),
        )
        for i, night in enumerate(nights)
    }


# --- snapshots --------------------------------------------------------------


async def _save(
    session: AsyncSession,
    hotel: Hotel,
    room_type: RoomType,
    version_row: PricingModel,
    night: _Night,
    scored: _Scored,
) -> RecommendationSnapshot:
    """Store a freshly priced night as a new snapshot."""
    return await recommendation_repo.create_recommendation_snapshot(
        session,
        hotel_id=hotel.id,
        room_type_id=room_type.id,
        stay_date=night.stay_date,
        model_id=version_row.id,
        rate=scored.rate,
        factors=explanation_to_json(scored.explanation),
        inputs=night.inputs,
    )


def _from_snapshot(
    snap: RecommendationSnapshot, hotel: Hotel, room_type: RoomType
) -> Recommendation:
    """A version_row snapshot, read back as a recommendation."""
    inputs = snap.inputs or {}  # empty on snapshots from before decision 0038
    return Recommendation(
        hotel_id=hotel.id,
        stay_date=snap.stay_date,
        room_type=room_type.name,
        room_type_id=room_type.id,
        lead_days=_lead_days(inputs),
        recommended_rate=snap.rate,
        explanation=explanation_from_json(snap.factors),
        model_id=snap.model_id,
        events=[_event_from_json(e) for e in inputs.get("events", [])],
        events_source=inputs.get("events_source"),
        snapshot_id=snap.id,
        priced_at=snap.created_at,
    )


def _unsaved(
    hotel: Hotel,
    room_type: RoomType,
    version_row: PricingModel,
    night: _Night,
    scored: _Scored,
) -> Recommendation:
    """A past night priced now; returned but never version_row."""
    return Recommendation(
        hotel_id=hotel.id,
        stay_date=night.stay_date,
        room_type=room_type.name,
        room_type_id=room_type.id,
        lead_days=_lead_days(night.inputs),
        recommended_rate=scored.rate,
        explanation=scored.explanation,
        model_id=version_row.id,
        events=night.events,
        events_source=night.events_source,
        snapshot_id=None,
        priced_at=datetime.now(UTC),
    )


def _lead_days(inputs: dict[str, Any]) -> int | None:
    """The days ahead a night was priced at, from its version_row inputs; None on
    snapshots from versions that didn't read them."""
    value = inputs.get("features", {}).get(LEAD)
    return None if value is None else int(value)
