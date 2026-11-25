from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Row,
    and_,
    delete,
    func,
    literal_column,
    not_,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import EventCategory, EventStatus, Source
from foresight.database.models.event import Event, EventObservation
from foresight.repository.pagination import fetch_page

_EVENTS = Event.__table__
_OBSERVATIONS = EventObservation.__table__


async def find_event_id_by_sighting(
    session: AsyncSession, *, source: Source, source_ref: str
) -> int | None:
    """Finds the event a source's record was last resolved to.

    Args:
        session (AsyncSession): The database session.
        source (Source): The source.
        source_ref (str): The source's own id for the record.

    Returns:
        int | None: The event's id, or None if the record wasn't seen before.
    """
    return await session.scalar(
        select(_OBSERVATIONS.c.event_id).where(
            _OBSERVATIONS.c.source == source,
            _OBSERVATIONS.c.source_ref == source_ref,
        )
    )


async def find_other_event_id_by_key(
    session: AsyncSession, *, dedupe_key: str, exclude_id: int
) -> int | None:
    """Finds another event already holding a dedupe key.

    Args:
        session (AsyncSession): The database session.
        dedupe_key (str): The key.
        exclude_id (int): The event to leave out.

    Returns:
        int | None: The other event's id, or None if there isn't one.
    """
    return await session.scalar(
        select(_EVENTS.c.id).where(
            _EVENTS.c.dedupe_key == dedupe_key, _EVENTS.c.id != exclude_id
        )
    )


async def merge_event_into(
    session: AsyncSession, *, from_id: int, into_id: int
) -> None:
    """Moves every sighting of one event onto another, then deletes the first.

    Args:
        session (AsyncSession): The database session.
        from_id (int): The event to delete.
        into_id (int): The event to keep.
    """
    await session.execute(
        update(_OBSERVATIONS)
        .where(_OBSERVATIONS.c.event_id == from_id)
        .values(event_id=into_id)
    )
    await session.execute(delete(_EVENTS).where(_EVENTS.c.id == from_id))


async def insert_or_touch_event(
    session: AsyncSession, row: Mapping[str, Any]
) -> tuple[int, bool]:
    """Inserts an event, or marks the one with its dedupe key as seen now.

    `xmax` is 0 only on a freshly inserted row, which tells new from existing.

    Args:
        session (AsyncSession): The database session.
        row (Mapping[str, Any]): The event's columns.

    Returns:
        tuple[int, bool]: The event's id, and whether it was inserted.
    """
    stmt = (
        insert(_EVENTS)
        .values(**row)
        .on_conflict_do_update(
            index_elements=[_EVENTS.c.dedupe_key],
            set_={"last_seen_at": func.clock_timestamp()},
        )
        .returning(_EVENTS.c.id, literal_column("(xmax = 0)").label("inserted"))
    )
    result = (await session.execute(stmt)).one()
    return result.id, result.inserted


async def lock_event(session: AsyncSession, event_id: int) -> Mapping[str, Any]:
    """Gets an event's columns, row-locked until the transaction ends.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event.

    Returns:
        Mapping[str, Any]: Its current column values.
    """
    result = await session.execute(
        select(_EVENTS).where(_EVENTS.c.id == event_id).with_for_update()
    )
    return result.mappings().one()


async def update_event(
    session: AsyncSession, event_id: int, changes: Mapping[str, Any]
) -> None:
    """Changes an event's columns and marks it as seen now.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event.
        changes (Mapping[str, Any]): The columns to change.
    """
    await session.execute(
        update(_EVENTS)
        .where(_EVENTS.c.id == event_id)
        .values(**changes, last_seen_at=func.clock_timestamp())
    )


async def list_other_sightings(
    session: AsyncSession, event_id: int, *, source: Source, source_ref: str
) -> Sequence[Row[tuple[Source, EventStatus | None, datetime | None, str]]]:
    """Lists every other sighting of an event.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event.
        source (Source): The source of the sighting to leave out.
        source_ref (str): Its id at that source.

    Returns:
        Sequence[Row[tuple[Source, EventStatus | None, datetime | None, str]]]:
            Each sighting's source, status, source_updated_at and source_ref.
    """
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
    """Records a source's sighting, keyed on the source and its own id.

    `captured_at` moves only when the payload, event or status changed, so it
    marks when this version of the record arrived, not every re-run.

    Args:
        session (AsyncSession): The database session.
        event_id (int): The event it resolved to.
        source (Source): The source.
        source_ref (str): The source's own id for the record.
        source_updated_at (datetime | None): When the source last changed it.
        status (EventStatus): What the sighting reported.
        payload (dict[str, Any]): The source's record, as it came.
    """
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
            where=or_(
                _OBSERVATIONS.c.payload.is_distinct_from(excluded.payload),
                _OBSERVATIONS.c.event_id.is_distinct_from(excluded.event_id),
                _OBSERVATIONS.c.status.is_distinct_from(excluded.status),
            ),
        )
    )


async def list_events(
    session: AsyncSession,
    *,
    city_id: int,
    start: date | None,
    end: date | None,
    exclude_statuses: Collection[EventStatus],
    limit: int,
    offset: int,
) -> tuple[Sequence[Event], int]:
    """Lists one page of a city's events overlapping a window.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        start (date | None): First night, inclusive; None for no limit.
        end (date | None): Last night, inclusive; None for no limit.
        exclude_statuses (Collection[EventStatus]): Statuses to leave out.
        limit (int): Most events to return.
        offset (int): Events to skip.

    Returns:
        tuple[Sequence[Event], int]: The page, by start date, and how many
            events there are.
    """
    stmt = select(Event).where(Event.city_id == city_id)
    if exclude_statuses:
        stmt = stmt.where(Event.status.not_in(exclude_statuses))
    if start is not None:
        stmt = stmt.where(Event.end_local_date >= start)
    if end is not None:
        stmt = stmt.where(Event.start_local_date <= end)
    stmt = stmt.order_by(Event.start_local_date, Event.id)
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def list_events_overlapping(
    session: AsyncSession,
    *,
    city_id: int,
    start: date,
    end: date,
    exclude_statuses: Collection[EventStatus],
    categories: Collection[EventCategory],
) -> Sequence[Event]:
    """Lists a city's events in some categories that overlap a window.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.
        exclude_statuses (Collection[EventStatus]): Statuses to leave out.
        categories (Collection[EventCategory]): Categories to keep.

    Returns:
        Sequence[Event]: The events.
    """
    result = await session.scalars(
        select(Event).where(
            Event.city_id == city_id,
            Event.end_local_date >= start,
            Event.start_local_date <= end,
            Event.status.not_in(exclude_statuses),
            Event.category.in_(categories),
        )
    )
    return result.all()


async def latest_payloads(
    session: AsyncSession, event_ids: Collection[int], *, source: Source
) -> dict[int, Mapping[str, Any]]:
    """Gets each event's most recently updated record from a source.

    Args:
        session (AsyncSession): The database session.
        event_ids (Collection[int]): The events.
        source (Source): The source.

    Returns:
        dict[int, Mapping[str, Any]]: Each event's record, by event id; events
            without one are left out.
    """
    if not event_ids:
        return {}
    result = await session.execute(
        select(_OBSERVATIONS.c.event_id, _OBSERVATIONS.c.payload)
        .where(
            _OBSERVATIONS.c.event_id.in_(event_ids),
            _OBSERVATIONS.c.source == source,
        )
        .distinct(_OBSERVATIONS.c.event_id)
        .order_by(
            _OBSERVATIONS.c.event_id,
            _OBSERVATIONS.c.source_updated_at.desc().nulls_last(),
        )
    )
    return dict(result.tuples().all())
