import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.config import settings
from foresight.database.enums import JobKind, JobStatus
from foresight.database.models.hotel import Hotel
from foresight.database.models.job import Job
from foresight.repository import job as job_repo
from foresight.services.errors import DomainError
from foresight.services.hotels.hotel import list_hotels
from foresight.services.jobs.job import start_events_job, start_train_job

log = logging.getLogger(__name__)

RETRY_AFTER = timedelta(hours=1)
SCHEDULED = {"scheduled": True}


async def start_due_jobs(session: AsyncSession) -> list[Job]:
    """Queues every hotel's routine jobs that are due, in the order they run.

    Events run first, so training learns from them; training runs only with
    SCHEDULED_TRAINING on. Prices aren't saved ahead: the calendar prices on
    request. Each job is due once a day at SCHEDULE_HOUR, hotel time (see
    `_due`). One that can't start, e.g. already queued or not configured, is
    skipped until the next check.

    Args:
        session (AsyncSession): The database session.

    Returns:
        list[Job]: The jobs queued.
    """
    routine: list[tuple[JobKind, Callable[[int], Awaitable[Job]]]]
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
    """Says whether a hotel's routine job is due.

    Due when no scheduled run has started since the latest SCHEDULE_HOUR that
    has passed, hotel time, or RETRY_AFTER a scheduled run that failed. Only
    scheduled runs count, so a manual one doesn't move it. A missed hour
    (server down or asleep) is caught up at the next check. A run that
    stopped on a quota waits for the next day, like a success.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel, with its city loaded.
        kind (JobKind): The job.
        now (datetime): The current time.

    Returns:
        bool: True if it should be queued now.
    """
    tz = ZoneInfo(hotel.city.timezone)
    local_now = now.astimezone(tz)
    slot = datetime.combine(local_now.date(), time(settings.schedule_hour), tzinfo=tz)
    if slot > local_now:
        slot -= timedelta(days=1)
    last = await job_repo.latest_finished_job(
        session, hotel_id=hotel.id, kind=kind, params=SCHEDULED
    )
    if last is None or last.created_at < slot:
        return True
    assert last.finished_at is not None
    return last.status == JobStatus.FAILED and last.finished_at + RETRY_AFTER <= now
