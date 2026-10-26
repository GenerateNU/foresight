"""Per-night views for the calendar and night detail: what a night holds.

Events come from `event.events_by_night`, the same rule the model uses, so what
the manager sees matches what drives the rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from foresight.services.domain import event as event_service
from foresight.services.domain import recommendation as recommendation_service
from foresight.services.errors import InvalidRequestError

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

# Each night is priced on its own, which loads the model, so a range is capped.
MAX_RANGE_NIGHTS = 62


@dataclass(frozen=True, slots=True)
class Night:
    """One night's events, with full details."""

    hotel_id: int
    stay_date: date
    events: list[event_service.NightEvent]


@dataclass(frozen=True, slots=True)
class NightRate:
    """One night's recommended rate and the names of the events affecting it."""

    stay_date: date
    recommended_rate: Decimal
    currency: str
    event_names: list[str]


async def get_events(session: AsyncSession, hotel_id: int, stay_date: date) -> Night:
    """The events affecting one night, largest first.

    Raises:
        NotFoundError: Unknown hotel.
    """
    by_night = await event_service.events_by_night(
        session, hotel_id, start=stay_date, end=stay_date
    )
    return Night(hotel_id, stay_date, by_night[stay_date])


async def recommendation_range(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date,
    end: date,
    room_type_id: int | None,
) -> list[NightRate]:
    """The recommended rate for each night in [start, end], with event names.

    Raises:
        NotFoundError: Unknown hotel or room type, or no active model.
        InvalidRequestError: `end` is before `start`, the range is longer than
            `MAX_RANGE_NIGHTS`, or the model wasn't trained on the room type.
    """
    if (end - start).days + 1 > MAX_RANGE_NIGHTS:
        raise InvalidRequestError(f"range is limited to {MAX_RANGE_NIGHTS} nights")
    by_night = await event_service.events_by_night(
        session, hotel_id, start=start, end=end
    )
    rates = []
    for stay_date, events in by_night.items():
        rec = await recommendation_service.get_recommendation(
            session, hotel_id, stay_date, room_type_id=room_type_id
        )
        rates.append(
            NightRate(
                stay_date, rec.recommended_rate, rec.currency, [e.title for e in events]
            )
        )
    return rates
