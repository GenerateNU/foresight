"""Events: merging sightings from several sources onto one canonical row.

PredictHQ is the only source today, but it can list the same real-world event
more than once. Each record is kept as an observation, and the `events` row
carries the values of whichever sighting ranks highest (see `_rank`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from foresight.database.enums import EventCategory, EventStatus, Source
from foresight.repository.signals import event as event_repo
from foresight.repository.upsert import Outcome
from foresight.services.domain.hotel import get_hotel
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.features import ATTENDED_CATEGORIES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.signals.event import Event
    from foresight.services.adapters.normalize import NormalizedEvent

# How much each source is trusted; a new source gets a rank here.
_PRECEDENCE = {Source.PREDICTHQ: 1}
# Withdrawn or called-off events don't count as demand.
_WITHDRAWN = (EventStatus.DELETED, EventStatus.CANCELLED)
_NEVER = datetime.min.replace(tzinfo=UTC)
# The categories the model counts on a night: attended events, plus the two
# holiday kinds it turns into flags (see `ml.features._event_features`).
_COUNTED = frozenset(
    {
        *(EventCategory(c) for c in ATTENDED_CATEGORIES),
        EventCategory.PUBLIC_HOLIDAYS,
        EventCategory.SCHOOL_HOLIDAYS,
    }
)


@dataclass(frozen=True, slots=True)
class NightEvent:
    """An event as it falls on one night."""

    event_id: int
    title: str
    venue: str | None
    category: EventCategory
    expected_attendance: int | None
    day_number: int  # 1-based position of this night within the event
    day_count: int  # nights the event spans; 1 for a single-day event


async def save_event(
    session: AsyncSession, city_id: int, event: NormalizedEvent
) -> Outcome:
    """Resolve `event` to its canonical row in `city_id`, write it, and record
    the sighting.

    Does not commit; the caller owns the transaction.
    """
    row = {**event.as_row(), "city_id": city_id}
    event_id = await event_repo.find_event_id_by_sighting(
        session, source=event.source, source_ref=event.source_ref
    )

    # Source identity must be checked before dedupe_key: a revised start date
    # changes the key, and resolving by key first would orphan the old row.
    if event_id is not None:
        event_id = await _absorb_key_collision(session, event_id, row["dedupe_key"])
        outcome = await _apply(session, event_id, event, row)
    else:
        event_id, inserted = await event_repo.insert_or_touch_event(session, row)
        outcome = (
            Outcome.NEW if inserted else await _apply(session, event_id, event, row)
        )

    await event_repo.upsert_observation(
        session,
        event_id=event_id,
        source=event.source,
        source_ref=event.source_ref,
        source_updated_at=event.source_updated_at,
        status=event.status,
        payload=event.payload,
    )
    return outcome


async def list_events(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Event], int]:
    """Live events in the hotel's city overlapping [start, end]; withdrawn ones
    are hidden."""
    hotel = await get_hotel(session, hotel_id)
    return await event_repo.list_events(
        session,
        city_id=hotel.city_id,
        start=start,
        end=end,
        exclude_statuses=_WITHDRAWN,
        limit=limit,
        offset=offset,
    )


async def events_by_night(
    session: AsyncSession, city_id: int, *, start: date, end: date
) -> dict[date, list[NightEvent]]:
    """The events affecting each night in [start, end], both inclusive.

    Uses the model's rule (decision 0032): live events in the city, of a
    category the model counts, on every night from their start to their end
    date. Every night in the range is a key, with an empty list when nothing
    affects it. Each night's events are largest first: expected attendance,
    then local rank; unknown values last.

    Raises:
        InvalidRequestError: `end` is before `start`.
    """
    if end < start:
        raise InvalidRequestError("end must not be before start")
    events = await event_repo.list_events_overlapping(
        session,
        city_id=city_id,
        start=start,
        end=end,
        exclude_statuses=_WITHDRAWN,
        categories=_COUNTED,
    )
    return _by_night(events, start, end)


def _by_night(
    events: Sequence[Event], start: date, end: date
) -> dict[date, list[NightEvent]]:
    by_night: dict[date, list[NightEvent]] = {
        start + timedelta(days=i): [] for i in range((end - start).days + 1)
    }
    # Largest first, so each night's list comes out in that order.
    for event in sorted(events, key=_importance):
        day_count = (event.end_local_date - event.start_local_date).days + 1
        first = max(event.start_local_date, start)
        last = min(event.end_local_date, end)
        for i in range((last - first).days + 1):
            night = first + timedelta(days=i)
            by_night[night].append(
                NightEvent(
                    event_id=event.id,
                    title=event.title,
                    venue=event.venue,
                    category=event.category,
                    expected_attendance=event.expected_attendance,
                    day_number=(night - event.start_local_date).days + 1,
                    day_count=day_count,
                )
            )
    return by_night


def _importance(event: Event) -> tuple[int, int, int]:
    """Sort key putting the biggest event first; unknown values sort last."""
    return (
        -(event.expected_attendance if event.expected_attendance is not None else -1),
        -(event.local_rank if event.local_rank is not None else -1),
        event.id,
    )


async def market_totals(
    session: AsyncSession, city_id: int
) -> tuple[dict[str, int], dict[str, int]]:
    """Events in the city by status, and their observations by source."""
    by_status = await event_repo.count_events_by_status(session, city_id)
    by_source = await event_repo.count_observations_by_source(session, city_id)
    return (
        {status.value: n for status, n in by_status.items()},
        {source.value: n for source, n in by_source.items()},
    )


async def _absorb_key_collision(
    session: AsyncSession, event_id: int, new_key: str
) -> int:
    """If a revision moved onto a key another sighting already holds, merge."""
    other_id = await event_repo.find_other_event_id_by_key(
        session, dedupe_key=new_key, exclude_id=event_id
    )
    if other_id is None:
        return event_id
    await event_repo.merge_event_into(session, from_id=event_id, into_id=other_id)
    return other_id


async def _apply(
    session: AsyncSession, event_id: int, event: NormalizedEvent, row: dict
) -> Outcome:
    current = await event_repo.lock_event(session, event_id)

    changes = {}
    if await _outranks_other_sightings(session, event_id, event):
        changes = {k: v for k, v in row.items() if current[k] != v}

    await event_repo.update_event(session, event_id, changes)
    return Outcome.UPDATED if changes else Outcome.UNCHANGED


async def _outranks_other_sightings(
    session: AsyncSession, event_id: int, event: NormalizedEvent
) -> bool:
    """Whether `event` is the sighting whose values the row should carry.

    Every sighting of a row is ranked the same way, so reruns settle on one
    winner instead of duplicate listings overwriting each other in turn. A
    deleted duplicate thus never takes down the live listing it shares a row
    with, on the first run or any later one.
    """
    others = await event_repo.list_other_sightings(
        session, event_id, source=event.source, source_ref=event.source_ref
    )
    mine = _rank(event.source, event.status, event.source_updated_at, event.source_ref)
    return all(mine > _rank(*other) for other in others)


def _rank(
    source: Source,
    status: EventStatus | None,
    updated_at: datetime | None,
    source_ref: str,
) -> tuple[int, bool, datetime, str]:
    """Structured sources first, then live listings, then the latest revision.

    source_ref only breaks exact ties, so the winner is stable across reruns.
    """
    return (
        _PRECEDENCE[Source(source)],
        status not in _WITHDRAWN,
        updated_at or _NEVER,
        source_ref,
    )
