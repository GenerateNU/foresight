"""Persist NormalizedEvents onto the canonical `events` row and its observations."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from foresight.database.models.external import Event, EventObservation
from foresight.ingest.normalize import EventStatus, Source

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.ingest.normalize import NormalizedEvent

_EVENTS = Event.__table__
_OBSERVATIONS = EventObservation.__table__

# Structured listings outrank dates and venues extracted from prose.
_PRECEDENCE = {Source.PREDICTHQ: 2, Source.ASKNEWS: 1}


class Outcome(StrEnum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


async def upsert_event(session: AsyncSession, event: NormalizedEvent) -> Outcome:
    """Resolve `event` to its canonical row, write it, and record the sighting.

    Does not commit; the caller owns the transaction.
    """
    row = event.as_row()
    event_id = await session.scalar(
        select(_OBSERVATIONS.c.event_id).where(
            _OBSERVATIONS.c.source == event.source,
            _OBSERVATIONS.c.source_ref == event.source_ref,
        )
    )

    # Source identity must be checked before dedupe_key: a revised start date
    # changes the key, and resolving by key first would orphan the old row.
    if event_id is not None:
        event_id = await _absorb_key_collision(session, event_id, row["dedupe_key"])
        outcome = await _apply(session, event_id, row, own_record=True)
    else:
        event_id, inserted = await _insert_or_find(session, row)
        outcome = (
            Outcome.NEW
            if inserted
            else await _apply(session, event_id, row, own_record=False)
        )

    await _record_observation(session, event, event_id)
    return outcome


async def _absorb_key_collision(
    session: AsyncSession, event_id: int, new_key: str
) -> int:
    """If a revision moved onto a key another sighting already holds, merge."""
    other_id = await session.scalar(
        select(_EVENTS.c.id).where(
            _EVENTS.c.dedupe_key == new_key, _EVENTS.c.id != event_id
        )
    )
    if other_id is None:
        return event_id

    await session.execute(
        update(_OBSERVATIONS)
        .where(_OBSERVATIONS.c.event_id == event_id)
        .values(event_id=other_id)
    )
    await session.execute(delete(_EVENTS).where(_EVENTS.c.id == event_id))
    return other_id


async def _insert_or_find(
    session: AsyncSession, row: Mapping[str, Any]
) -> tuple[int, bool]:
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


async def _apply(
    session: AsyncSession,
    event_id: int,
    row: Mapping[str, Any],
    *,
    own_record: bool,
) -> Outcome:
    current = (
        (
            await session.execute(
                select(_EVENTS).where(_EVENTS.c.id == event_id).with_for_update()
            )
        )
        .mappings()
        .one()
    )

    changes: dict[str, Any] = {}
    if _may_overwrite(current, row, own_record=own_record):
        changes = {k: v for k, v in row.items() if current[k] != v}

    await session.execute(
        update(_EVENTS)
        .where(_EVENTS.c.id == event_id)
        .values(**changes, last_seen_at=func.clock_timestamp())
    )
    return Outcome.UPDATED if changes else Outcome.UNCHANGED


def _may_overwrite(
    current: Mapping[str, Any], row: Mapping[str, Any], *, own_record: bool
) -> bool:
    # Another record's deletion (e.g. a PredictHQ duplicate that collapses onto
    # the surviving listing) must not take down an event seen independently.
    if not own_record and row["status"] is EventStatus.DELETED:
        return False
    incoming = _PRECEDENCE[row["primary_source"]]
    return incoming >= _PRECEDENCE[Source(current["primary_source"])]


async def _record_observation(
    session: AsyncSession, event: NormalizedEvent, event_id: int
) -> None:
    stmt = insert(_OBSERVATIONS).values(
        event_id=event_id,
        source=event.source,
        source_ref=event.source_ref,
        source_updated_at=event.source_updated_at,
        payload=event.payload,
    )
    excluded = stmt.excluded
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[_OBSERVATIONS.c.source, _OBSERVATIONS.c.source_ref],
            set_={
                "event_id": excluded.event_id,
                "source_updated_at": excluded.source_updated_at,
                "payload": excluded.payload,
                "captured_at": func.clock_timestamp(),
            },
            # captured_at marks when this payload version arrived, not every rerun.
            where=or_(
                _OBSERVATIONS.c.payload.is_distinct_from(excluded.payload),
                _OBSERVATIONS.c.event_id.is_distinct_from(excluded.event_id),
            ),
        )
    )
