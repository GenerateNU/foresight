from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import EventCategory, EventStatus, JobKind, Source
from foresight.database.models.signals.event import Event
from foresight.repository import job as job_repo
from foresight.repository.signals import event as event_repo
from foresight.repository.upsert import Outcome
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.normalize import NormalizedEvent
from foresight.services.domain.window import Window
from foresight.services.errors import InvalidRequestError
from foresight.services.ml.features import ATTENDED_CATEGORIES

_PRECEDENCE = {Source.PREDICTHQ: 1}
_WITHDRAWN = (EventStatus.DELETED, EventStatus.CANCELLED)
_NEVER = datetime.min.replace(tzinfo=UTC)
_COUNTED = frozenset(EventCategory(c) for c in ATTENDED_CATEGORIES)


@dataclass(frozen=True, slots=True)
class NightEvent:
    """An event as it falls on one night.

    Attributes:
        event_id (int): The event.
        title (str): Its title.
        venue (str | None): Where.
        category (EventCategory): What kind of event.
        expected_attendance (int | None): How many people.
        day_number (int): This night's place in the event, from 1.
        day_count (int): Nights the event spans; 1 for a single day.
    """

    event_id: int
    title: str
    venue: str | None
    category: EventCategory
    expected_attendance: int | None
    day_number: int
    day_count: int


async def save_event(
    session: AsyncSession, city_id: int, event: NormalizedEvent
) -> Outcome:
    """Saves an event onto its canonical row and records the sighting.

    One real-world event can be listed more than once, so each record is kept
    as an observation and the `events` row carries the values of whichever
    sighting ranks highest (see `_rank`). The sighting is looked up by source
    id before dedupe key: a revised start date changes the key, and resolving
    by key first would orphan the old row. Does not commit.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The event's city.
        event (NormalizedEvent): The record.

    Returns:
        Outcome: Whether the row is new, updated or unchanged.
    """
    row = {**event.as_row(), "city_id": city_id}
    event_id = await event_repo.find_event_id_by_sighting(
        session, source=event.source, source_ref=event.source_ref
    )
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
    """Lists the live events in the hotel's city overlapping a range.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date | None): First night, inclusive; None for no limit.
        end (date | None): Last night, inclusive; None for no limit.
        limit (int): Page size.
        offset (int): Rows to skip.

    Returns:
        tuple[Sequence[Event], int]: The page, and the total; withdrawn
            events are hidden.

    Raises:
        NotFoundError: The hotel doesn't exist.
    """
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


async def counted_events(
    session: AsyncSession, city_id: int, *, start: date, end: date
) -> Sequence[Event]:
    """Lists the events the model counts that fall on any night in a range.

    Live events in the city, of an attended category; holidays come from the
    `holidays` library, not from events.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        Sequence[Event]: The events.
    """
    return await event_repo.list_events_overlapping(
        session,
        city_id=city_id,
        start=start,
        end=end,
        exclude_statuses=_WITHDRAWN,
        categories=_COUNTED,
    )


async def fetched_nights(
    session: AsyncSession, city_id: int, *, start: date, end: date
) -> set[date]:
    """Lists the nights in a range an events backfill has fetched for the city.

    Other nights are unknown, not quiet. Only backfills count: the routine
    refresh asks for what changed, not for any nights. Each job counts for
    the months it saved, except months PredictHQ cut short or that came back
    empty: a month with nothing points to a plan limit, not a quiet city.
    Jobs recorded before `fetched` was tracked count for nothing; older ones
    with `backwards` false walked oldest month first.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        set[date]: The nights fetched.
    """
    jobs = await job_repo.list_finished_jobs_in_city(
        session, city_id=city_id, kind=JobKind.EVENTS, params={"mode": "window"}
    )
    nights: set[date] = set()
    for job in jobs:
        if not job.progress.get("fetched"):
            continue
        skipped = job.progress.get("empty_months", []) + job.progress.get(
            "overflowed_months", []
        )
        months = Window.from_params(job.params).months()
        if job.params.get("backwards") is False:
            months.reverse()
        for first, last in months[: job.progress.get("months_done", 0)]:
            if [first.isoformat(), last.isoformat()] in skipped:
                continue
            first, last = max(first, start), min(last, end)
            nights.update(
                first + timedelta(days=i) for i in range((last - first).days + 1)
            )
    return nights


async def events_by_night(
    session: AsyncSession, city_id: int, *, start: date, end: date
) -> dict[date, list[NightEvent]]:
    """Lists the events affecting each night in a range.

    Uses the model's rule: the events `counted_events` finds, on every night
    from their start to their end date.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        dict[date, list[NightEvent]]: Every night in the range, with an empty
            list when nothing affects it. Each night's events are largest
            first: expected attendance, then local rank; unknown values last.

    Raises:
        InvalidRequestError: `end` is before `start`.
    """
    if end < start:
        raise InvalidRequestError("end must not be before start")
    events = await counted_events(session, city_id, start=start, end=end)
    return _by_night(events, start, end)


def _by_night(
    events: Sequence[Event], start: date, end: date
) -> dict[date, list[NightEvent]]:
    """Spreads events over the nights in a range, largest first.

    Args:
        events (Sequence[Event]): The events.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        dict[date, list[NightEvent]]: Every night in the range.
    """
    by_night: dict[date, list[NightEvent]] = {
        start + timedelta(days=i): [] for i in range((end - start).days + 1)
    }
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
    """Sorts the biggest event first; unknown values sort last.

    Args:
        event (Event): The event.

    Returns:
        tuple[int, int, int]: The sort key.
    """
    return (
        -(event.expected_attendance if event.expected_attendance is not None else -1),
        -(event.local_rank if event.local_rank is not None else -1),
        event.id,
    )


async def _absorb_key_collision(
    session: AsyncSession, event_id: int, new_key: str
) -> int:
    """Merges the row into another that already holds its new dedupe key.

    A revision can move an event onto a key another sighting holds.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event's row.
        new_key (str): Its new dedupe key.

    Returns:
        int: The row the event now lives on.
    """
    other_id = await event_repo.find_other_event_id_by_key(
        session, dedupe_key=new_key, exclude_id=event_id
    )
    if other_id is None:
        return event_id
    await event_repo.merge_event_into(session, from_id=event_id, into_id=other_id)
    return other_id


async def _apply(
    session: AsyncSession,
    event_id: int,
    event: NormalizedEvent,
    row: dict[str, Any],
) -> Outcome:
    """Writes a sighting's values onto its row, if it outranks the others.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event's row.
        event (NormalizedEvent): The sighting.
        row (dict[str, Any]): Its column values.

    Returns:
        Outcome: Whether the row changed.
    """
    current = await event_repo.lock_event(session, event_id)
    changes = {}
    if await _outranks_other_sightings(session, event_id, event):
        changes = {k: v for k, v in row.items() if current[k] != v}

    await event_repo.update_event(session, event_id, changes)
    return Outcome.UPDATED if changes else Outcome.UNCHANGED


async def _outranks_other_sightings(
    session: AsyncSession, event_id: int, event: NormalizedEvent
) -> bool:
    """Says whether a sighting is the one whose values the row should carry.

    Every sighting of a row is ranked the same way, so reruns settle on one
    winner instead of duplicate listings overwriting each other in turn. A
    deleted duplicate thus never takes down the live listing it shares a row
    with.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event's row.
        event (NormalizedEvent): The sighting.

    Returns:
        bool: True if it outranks every other sighting.
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
    """Ranks a sighting: trusted source, then live, then latest revision.

    Args:
        source (Source): Where it came from; `_PRECEDENCE` ranks sources.
        status (EventStatus | None): Withdrawn ranks below live.
        updated_at (datetime | None): When the source last changed it.
        source_ref (str): Only breaks exact ties, so the winner is stable.

    Returns:
        tuple[int, bool, datetime, str]: Higher ranks first.
    """
    return (
        _PRECEDENCE[Source(source)],
        status not in _WITHDRAWN,
        updated_at or _NEVER,
        source_ref,
    )
