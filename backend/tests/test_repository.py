"""Upsert resolution order against a real Postgres; skipped when none is reachable."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from foresight.config import settings
from foresight.database.models.external import Event, EventObservation
from foresight.ingest.normalize import EventStatus, NormalizedEvent, Source
from foresight.ingest.repository import Outcome, upsert_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(settings.database_url)
    try:
        conn = await engine.connect()
    except (OSError, ConnectionError) as exc:
        await engine.dispose()
        pytest.skip(f"Postgres unavailable: {exc}")

    trans = await conn.begin()
    async with AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint"
    ) as session:
        # Counts below assume an empty table; real ingested rows come back on
        # rollback.
        await session.execute(delete(EventObservation))
        await session.execute(delete(Event))
        yield session
    await trans.rollback()
    await conn.close()
    await engine.dispose()


def _phq(**overrides: object) -> NormalizedEvent:
    base: dict[str, object] = {
        "source": Source.PREDICTHQ,
        "source_ref": "phq-test-1",
        "title": "Hozier",
        "city": "Dublin",
        "start_local_date": date(2026, 11, 14),
        "end_local_date": date(2026, 11, 14),
        "timezone": "Europe/Dublin",
        "local_rank": 71,
        "payload": {"id": "phq-test-1"},
    }
    return NormalizedEvent(**(base | overrides))  # type: ignore[arg-type]


def _news(**overrides: object) -> NormalizedEvent:
    base: dict[str, object] = {
        "source": Source.ASKNEWS,
        "source_ref": "https://example.test/hozier-dublin",
        "title": "Hozier (Live)",
        "city": "Dublin, Ireland",
        "start_local_date": date(2026, 11, 14),
        "end_local_date": date(2026, 11, 14),
        "venue": "Somewhere Vague",
        "confidence": 0.6,
        "status": EventStatus.PROVISIONAL,
        "payload": {"url": "https://example.test/hozier-dublin"},
    }
    return NormalizedEvent(**(base | overrides))  # type: ignore[arg-type]


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def _only_event(session: AsyncSession) -> Event:
    return (
        await session.scalars(select(Event).execution_options(populate_existing=True))
    ).one()


async def test_start_date_revision_updates_the_row_instead_of_orphaning_it(
    session: AsyncSession,
) -> None:
    assert await upsert_event(session, _phq()) is Outcome.NEW
    first = await _only_event(session)
    first_id, first_seen, first_last = first.id, first.first_seen_at, first.last_seen_at

    revised = _phq(
        start_local_date=date(2026, 11, 15),
        end_local_date=date(2026, 11, 15),
        payload={"id": "phq-test-1", "rev": 2},
    )
    assert await upsert_event(session, revised) is Outcome.UPDATED

    assert await _count(session, Event) == 1
    assert await _count(session, EventObservation) == 1
    event = await _only_event(session)
    assert event.id == first_id
    assert event.start_local_date == date(2026, 11, 15)
    assert event.dedupe_key == revised.dedupe_key
    assert event.first_seen_at == first_seen
    assert event.last_seen_at > first_last


async def test_identical_rerun_is_unchanged_but_still_bumps_last_seen(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())
    before = (await _only_event(session)).last_seen_at

    assert await upsert_event(session, _phq()) is Outcome.UNCHANGED
    assert await _count(session, Event) == 1
    assert await _count(session, EventObservation) == 1
    assert (await _only_event(session)).last_seen_at > before


async def test_second_source_attaches_to_the_existing_event(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())

    # AskNews is outranked, so the PredictHQ values stand.
    assert await upsert_event(session, _news()) is Outcome.UNCHANGED

    assert await _count(session, Event) == 1
    assert await _count(session, EventObservation) == 2
    event = await _only_event(session)
    assert event.primary_source is Source.PREDICTHQ
    assert event.venue is None
    assert event.status is EventStatus.ACTIVE


async def test_higher_precedence_source_takes_over_a_text_extracted_event(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _news())

    assert await upsert_event(session, _phq()) is Outcome.UPDATED
    event = await _only_event(session)
    assert event.primary_source is Source.PREDICTHQ
    assert event.confidence == 1.0
    assert event.status is EventStatus.ACTIVE


async def test_revision_onto_an_existing_key_merges_rather_than_duplicates(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())
    # An article already reported the date PredictHQ is about to move to.
    await upsert_event(
        session,
        _news(start_local_date=date(2026, 11, 15), end_local_date=date(2026, 11, 15)),
    )
    assert await _count(session, Event) == 2

    await upsert_event(
        session,
        _phq(start_local_date=date(2026, 11, 15), end_local_date=date(2026, 11, 15)),
    )

    assert await _count(session, Event) == 1
    event = await _only_event(session)
    assert event.primary_source is Source.PREDICTHQ
    linked = await session.scalars(select(EventObservation.event_id))
    assert set(linked) == {event.id}


async def test_deletion_of_a_known_record_marks_the_event_deleted(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())

    deleted = _phq(status=EventStatus.DELETED, payload={"state": "deleted"})
    assert await upsert_event(session, deleted) is Outcome.UPDATED
    assert (await _only_event(session)).status is EventStatus.DELETED


async def test_another_records_deletion_does_not_kill_a_live_event(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())

    duplicate = _phq(
        source_ref="phq-test-dupe",
        status=EventStatus.DELETED,
        payload={"deleted_reason": "duplicate"},
    )
    assert await upsert_event(session, duplicate) is Outcome.UNCHANGED
    assert (await _only_event(session)).status is EventStatus.ACTIVE
    assert await _count(session, EventObservation) == 2


async def test_observation_payload_tracks_the_latest_revision(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())
    updated_at = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
    await upsert_event(
        session,
        _phq(payload={"id": "phq-test-1", "rev": 2}, source_updated_at=updated_at),
    )

    obs = (
        await session.scalars(
            select(EventObservation).execution_options(populate_existing=True)
        )
    ).one()
    assert obs.payload == {"id": "phq-test-1", "rev": 2}
    assert obs.source_updated_at == updated_at


async def test_deleted_duplicate_stays_harmless_on_every_rerun(
    session: AsyncSession,
) -> None:
    live = _phq()
    duplicate = _phq(source_ref="phq-test-dupe", status=EventStatus.DELETED)

    for _ in range(3):
        assert await upsert_event(session, live) in {Outcome.NEW, Outcome.UNCHANGED}
        assert await upsert_event(session, duplicate) is Outcome.UNCHANGED
        assert (await _only_event(session)).status is EventStatus.ACTIVE


async def test_live_duplicates_settle_on_the_latest_revision(
    session: AsyncSession,
) -> None:
    older = _phq(
        expected_attendance=210,
        source_updated_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    newer = _phq(
        source_ref="phq-test-dupe",
        expected_attendance=211,
        source_updated_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    await upsert_event(session, older)
    assert await upsert_event(session, newer) is Outcome.UPDATED

    # A rerun must not flip the row back and forth between the two listings.
    assert await upsert_event(session, older) is Outcome.UNCHANGED
    assert await upsert_event(session, newer) is Outcome.UNCHANGED
    assert (await _only_event(session)).expected_attendance == 211


async def test_live_listing_restores_an_event_its_duplicate_deleted(
    session: AsyncSession,
) -> None:
    # As left behind before sightings recorded their status.
    await upsert_event(session, _phq(source_ref="phq-test-dupe"))
    await upsert_event(session, _phq())
    await session.execute(EventObservation.__table__.update().values(status=None))
    await session.execute(Event.__table__.update().values(status=EventStatus.DELETED))

    await upsert_event(
        session, _phq(source_ref="phq-test-dupe", status=EventStatus.DELETED)
    )
    assert await upsert_event(session, _phq()) is Outcome.UPDATED
    assert (await _only_event(session)).status is EventStatus.ACTIVE


async def test_structured_deletion_outranks_a_live_article(
    session: AsyncSession,
) -> None:
    await upsert_event(session, _phq())
    await upsert_event(session, _news())

    deleted = _phq(status=EventStatus.DELETED)
    assert await upsert_event(session, deleted) is Outcome.UPDATED
    assert (await _only_event(session)).status is EventStatus.DELETED
