import math
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import EventCategory
from foresight.database.models.hotel import Hotel, RoomType
from foresight.database.models.model import PricingModel
from foresight.database.models.recommendation import RecommendationSnapshot
from foresight.repository import hotel as hotel_repo
from foresight.repository import recommendation as recommendation_repo
from foresight.services.errors import InvalidRequestError
from foresight.services.events import event as event_service
from foresight.services.events.event import NightEvent
from foresight.services.hotels.city import local_today
from foresight.services.hotels.hotel import get_hotel
from foresight.services.ml.features import LEAD
from foresight.services.pricing.inputs import build_inputs
from foresight.services.pricing.model import get_active_model, load_model
from foresight.services.recommendations.explanation import (
    Explanation,
    explain_rate,
    explanation_from_json,
    explanation_to_json,
    money,
)
from foresight.services.recommendations.feedback import current_feedback

MAX_NIGHTS = 90


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One night's rate, why, and what it was priced from.

    Attributes:
        hotel_id (int): The hotel.
        stay_date (date): The night.
        room_type (str): The room type's name.
        room_type_id (int): The room type.
        lead_days (int | None): Days from today it was priced at; None on old
            snapshots.
        recommended_rate (Decimal): The rate, before VAT.
        explanation (Explanation): Why.
        model_id (int): The version that priced it.
        events (list[NightEvent]): The events on the night, largest first.
        events_source (str | None): "fetched" or "missing"; None on old
            snapshots.
        snapshot_id (int | None): None for a past night priced but not saved.
        priced_at (datetime): When the model produced this rate.
        manager_rate (Decimal | None): The rate the manager set; None if they
            haven't. Read live, never stored in a snapshot, so it never
            triggers a new one.
    """

    hotel_id: int
    stay_date: date
    room_type: str
    room_type_id: int
    lead_days: int | None
    recommended_rate: Decimal
    explanation: Explanation
    model_id: int
    events: list[NightEvent]
    events_source: str | None
    snapshot_id: int | None
    priced_at: datetime
    manager_rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _Night:
    """A night's inputs, before any model runs.

    Attributes:
        stay_date (date): The night.
        features (pd.DataFrame): The model's input, one row.
        events (list[NightEvent]): The events on the night.
        events_source (str): "fetched" or "missing".
        inputs (dict[str, Any]): What's stored with the snapshot.
    """

    stay_date: date
    features: pd.DataFrame
    events: list[NightEvent]
    events_source: str
    inputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Scored:
    """What the model said about one night.

    Attributes:
        rate (Decimal): The rate, in cents.
        explanation (Explanation): Why.
    """

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
    """Recommends a rate for each night in a range, from the active model.

    Reads only what's already ingested; a night with missing data gets an
    empty input, which the model learned an effect for. Days booked ahead are
    an input: the rate is what the night would sell for if booked today, so a
    future night's inputs change daily. A night whose latest snapshot has the
    same model and inputs returns it, since that gives the same price; the
    rest are scored in one batch and, from today on, saved as new snapshots.
    Past nights are never saved after the fact.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        room_type_id (int | None): The room type; None for the one the model
            prices.

    Returns:
        list[Recommendation]: One per night, oldest first.

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


#          ╭──────────────────────────────────────────────────────────╮
#          │                          Inputs                          │
#          ╰──────────────────────────────────────────────────────────╯


async def _room_type(
    session: AsyncSession, version_row: PricingModel, room_type_id: int | None
) -> RoomType:
    """Gets the room type the active version prices.

    Args:
        session (AsyncSession): The database session.
        version_row (PricingModel): The active version.
        room_type_id (int | None): The room type asked for, if any.

    Returns:
        RoomType: The room type.

    Raises:
        InvalidRequestError: The version predates room types and prices
            none, or `room_type_id` is another room type.
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
    assert room_type is not None
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
    """Turns a feature value into plain JSON.

    Args:
        value (Any): The value, possibly a numpy scalar.

    Returns:
        Any: The value unwrapped; NaN as None.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):
        return _plain(value.item())
    if isinstance(value, bool | int | float):
        return value
    return None if pd.isna(value) else str(value)


def _event_json(event: NightEvent) -> dict[str, Any]:
    """Stores a night's event as JSON.

    Args:
        event (NightEvent): The event.

    Returns:
        dict[str, Any]: The JSON.
    """
    return {**asdict(event), "category": event.category.value}


def _event_from_json(data: dict[str, Any]) -> NightEvent:
    """Reads a night's event stored by `_event_json`.

    Args:
        data (dict[str, Any]): The JSON.

    Returns:
        NightEvent: The event.
    """
    return NightEvent(**{**data, "category": EventCategory(data["category"])})


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Scoring                          │
#          ╰──────────────────────────────────────────────────────────╯


async def _score(
    session: AsyncSession,
    version_row: PricingModel,
    nights: list[_Night],
) -> dict[date, _Scored]:
    """Runs the model once over every night given.

    Loads the model only if there is something to score.

    Args:
        session (AsyncSession): The database session.
        version_row (PricingModel): The active version.
        nights (list[_Night]): The nights to price.

    Returns:
        dict[date, _Scored]: Each night's rate and explanation.
    """
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


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Snapshots                         │
#          ╰──────────────────────────────────────────────────────────╯


async def _save(
    session: AsyncSession,
    hotel: Hotel,
    room_type: RoomType,
    version_row: PricingModel,
    night: _Night,
    scored: _Scored,
) -> RecommendationSnapshot:
    """Stores a freshly priced night as a new snapshot.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        room_type (RoomType): The room type.
        version_row (PricingModel): The version that priced it.
        night (_Night): The night and its inputs.
        scored (_Scored): The rate and explanation.

    Returns:
        RecommendationSnapshot: The new snapshot.
    """
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
    """Reads a stored snapshot back as a recommendation.

    Args:
        snap (RecommendationSnapshot): The snapshot; old ones have no inputs.
        hotel (Hotel): The hotel.
        room_type (RoomType): The room type.

    Returns:
        Recommendation: The recommendation.
    """
    inputs = snap.inputs or {}
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
    """Builds the recommendation for a past night priced now but not stored.

    Args:
        hotel (Hotel): The hotel.
        room_type (RoomType): The room type.
        version_row (PricingModel): The version that priced it.
        night (_Night): The night and its inputs.
        scored (_Scored): The rate and explanation.

    Returns:
        Recommendation: The recommendation, without a snapshot.
    """
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
    """Reads the days ahead a night was priced at from its stored inputs.

    Args:
        inputs (dict[str, Any]): The snapshot's inputs.

    Returns:
        int | None: The days; None for versions that didn't read them.
    """
    value = inputs.get("features", {}).get(LEAD)
    return None if value is None else int(value)
