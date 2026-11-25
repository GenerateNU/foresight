"""The daily routine: which jobs are due for each hotel, and queueing them."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from foresight.config import settings
from foresight.database.enums import JobKind, JobStatus
from foresight.repository import job as job_repo
from foresight.services.domain.hotel import list_hotels
from foresight.services.errors import DomainError
from foresight.services.job import start_events_job, start_train_job

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.job import Job

log = logging.getLogger(__name__)

RETRY_AFTER = timedelta(hours=1)
SCHEDULED = {"scheduled": True}


async def start_due_jobs(session: AsyncSession) -> list[Job]:
    """Queue every hotel's routine jobs that are due, in the order they run.

    Each is due once a day at SCHEDULE_HOUR, hotel time (`_due`). One that
    can't start (already queued, not configured) is skipped until the next
    check.
    """
    # (kind, how to start its scheduled run)
    routine: list[tuple[JobKind, Callable[[int], Awaitable[Job]]]]
    # Events first, so training learns from them. Weather was removed (0081),
    # and prices aren't saved ahead: the calendar prices on request (0084).
    routine = [
        (
            JobKind.EVENTS,
            lambda h: start_events_job(
                session, h, start=None, end=None, scheduled=True
            ),
        ),
        *(
            [
                (
                    JobKind.TRAIN,
                    lambda h: start_train_job(
                        session,
                        h,
                        description="scheduled",
                        start=None,
                        end=None,
                        activate=True,
                        ebm_params={},
                        scheduled=True,
                    ),
                )
            ]
            if settings.scheduled_training
            else []
        ),
    ]

    queued: list[Job] = []
    now = datetime.now(UTC)
    for hotel in await list_hotels(session):
        for kind, start in routine:
            if not await _due(session, hotel, kind, now):
                continue
            try:
                queued.append(await start(hotel.id))
            except DomainError as exc:
                log.info("hotel %s: %s not started: %s", hotel.id, kind.value, exc)
    return queued


async def _due(
    session: AsyncSession, hotel: Hotel, kind: JobKind, now: datetime
) -> bool:
    """Due once a day at SCHEDULE_HOUR, hotel time, or RETRY_AFTER a scheduled
    run that failed. Only scheduled runs count, so a manual one doesn't move
    it. A missed hour (server down or asleep) is caught up at the next check.
    A run that stopped on a quota waits for the next day, like a success."""
    tz = ZoneInfo(hotel.city.timezone)
    local_now = now.astimezone(tz)
    # The latest scheduled time that has passed: today's, or yesterday's if
    # today's hasn't come yet.
    slot = datetime.combine(local_now.date(), time(settings.schedule_hour), tzinfo=tz)
    if slot > local_now:
        slot -= timedelta(days=1)
    last = await job_repo.latest_finished_job(
        session, hotel_id=hotel.id, kind=kind, params=SCHEDULED
    )
    if last is None or last.created_at < slot:
        return True
    assert last.finished_at is not None  # the query only returns finished jobs
    return last.status == JobStatus.FAILED and last.finished_at + RETRY_AFTER <= now
