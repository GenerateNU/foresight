"""Data access for `events` and `event_observations`.

Plain reads and writes only. Deciding which sighting's values an event row
carries is business logic and lives in `services/event.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, literal_column, not_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from foresight.database.models.event import Event, EventObservation
from foresight.repository.pagination import fetch_page

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from datetime import date, datetime

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.enums import EventStatus, Source

_EVENTS = Event.__table__
_OBSERVATIONS = EventObservation.__table__


async def find_event_id_by_sighting(
    session: AsyncSession, *, source: Source, source_ref: str
) -> int | None:
    """The event a source's record was last resolved to, if it was seen before."""
    return await session.scalar(
        select(_OBSERVATIONS.c.event_id).where(
            _OBSERVATIONS.c.source == source,
            _OBSERVATIONS.c.source_ref == source_ref,
        )
    )


async def find_other_event_id_by_key(
    session: AsyncSession, *, dedupe_key: str, exclude_id: int
) -> int | None:
    """Another event already holding `dedupe_key`, if any."""
    return await session.scalar(
        select(_EVENTS.c.id).where(
            _EVENTS.c.dedupe_key == dedupe_key, _EVENTS.c.id != exclude_id
        )
    )


async def merge_event_into(
    session: AsyncSession, *, from_id: int, into_id: int
) -> None:
    """Move every observation of `from_id` onto `into_id`, then delete `from_id`."""
    await session.execute(
        update(_OBSERVATIONS)
        .where(_OBSERVATIONS.c.event_id == from_id)
        .values(event_id=into_id)
    )
    await session.execute(delete(_EVENTS).where(_EVENTS.c.id == from_id))


async def insert_or_touch_event(
    session: AsyncSession, row: Mapping[str, Any]
) -> tuple[int, bool]:
    """Insert `row`, or bump `last_seen_at` on the row with its dedupe_key.

    Returns the event id and whether it was newly inserted.
    """
    stmt = (
        insert(_EVENTS)
        .values(**row)
        .on_conflict_do_update(
            index_elements=[_EVENTS.c.dedupe_key],
            set_={"last_seen_at": func.clock_timestamp()},
        )
        # xmax is 0 only on a freshly inserted tuple, never on a conflict update.
        .returning(_EVENTS.c.id, literal_column("(xmax = 0)").label("inserted"))
    )
    result = (await session.execute(stmt)).one()
    return result.id, result.inserted


async def lock_event(session: AsyncSession, event_id: int) -> Mapping[str, Any]:
    """The event's current column values, row-locked until the transaction ends."""
    result = await session.execute(
        select(_EVENTS).where(_EVENTS.c.id == event_id).with_for_update()
    )
    return result.mappings().one()


async def update_event(
    session: AsyncSession, event_id: int, changes: Mapping[str, Any]
) -> None:
    """Apply `changes` and mark the event as seen now."""
    await session.execute(
        update(_EVENTS)
        .where(_EVENTS.c.id == event_id)
        .values(**changes, last_seen_at=func.clock_timestamp())
    )


async def list_other_sightings(
    session: AsyncSession, event_id: int, *, source: Source, source_ref: str
) -> Sequence[Row[tuple[Source, EventStatus | None, datetime | None, str]]]:
    """(source, status, source_updated_at, source_ref) of every other sighting."""
    result = await session.execute(
        select(
            _OBSERVATIONS.c.source,
            _OBSERVATIONS.c.status,
            _OBSERVATIONS.c.source_updated_at,
            _OBSERVATIONS.c.source_ref,
        ).where(
            _OBSERVATIONS.c.event_id == event_id,
            not_(
                and_(
                    _OBSERVATIONS.c.source == source,
                    _OBSERVATIONS.c.source_ref == source_ref,
                )
            ),
        )
    )
    return result.all()


async def upsert_observation(
    session: AsyncSession,
    *,
    event_id: int,
    source: Source,
    source_ref: str,
    source_updated_at: datetime | None,
    status: EventStatus,
    payload: dict[str, Any],
) -> None:
    """Record a source's sighting, keyed on (source, source_ref)."""
    stmt = insert(_OBSERVATIONS).values(
        event_id=event_id,
        source=source,
        source_ref=source_ref,
        source_updated_at=source_updated_at,
        status=status,
        payload=payload,
    )
    excluded = stmt.excluded
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[_OBSERVATIONS.c.source, _OBSERVATIONS.c.source_ref],
            set_={
                "event_id": excluded.event_id,
                "source_updated_at": excluded.source_updated_at,
                "status": excluded.status,
                "payload": excluded.payload,
                "captured_at": func.clock_timestamp(),
            },
            # captured_at marks when this payload version arrived, not every rerun.
            where=or_(
                _OBSERVATIONS.c.payload.is_distinct_from(excluded.payload),
                _OBSERVATIONS.c.event_id.is_distinct_from(excluded.event_id),
                _OBSERVATIONS.c.status.is_distinct_from(excluded.status),
            ),
        )
    )


async def count_events_by_status(
    session: AsyncSession, city_slug: str
) -> dict[EventStatus, int]:
    result = await session.execute(
        select(Event.status, func.count())
        .where(Event.city_slug == city_slug)
        .group_by(Event.status)
    )
    return dict(result.tuples().all())


async def count_observations_by_source(
    session: AsyncSession, city_slug: str
) -> dict[Source, int]:
    result = await session.execute(
        select(EventObservation.source, func.count())
        .join(Event, EventObservation.event_id == Event.id)
        .where(Event.city_slug == city_slug)
        .group_by(EventObservation.source)
    )
    return dict(result.tuples().all())


async def list_events(
    session: AsyncSession,
    *,
    city_slug: str,
    start: date | None,
    end: date | None,
    exclude_statuses: Collection[EventStatus],
    limit: int,
    offset: int,
) -> tuple[Sequence[Event], int]:
    """Events whose inclusive local-date range overlaps [start, end]."""
    stmt = select(Event).where(Event.city_slug == city_slug)
    if exclude_statuses:
        stmt = stmt.where(Event.status.not_in(exclude_statuses))
    if start is not None:
        stmt = stmt.where(Event.end_local_date >= start)
    if end is not None:
        stmt = stmt.where(Event.start_local_date <= end)
    stmt = stmt.order_by(Event.start_local_date, Event.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)
