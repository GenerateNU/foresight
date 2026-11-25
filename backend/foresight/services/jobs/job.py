from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.config import settings
from foresight.database.enums import JobKind, JobStatus
from foresight.database.models.hotel import Hotel
from foresight.database.models.job import Job
from foresight.repository import job as job_repo
from foresight.services.bookings import uploads as file_ingest
from foresight.services.errors import ConflictError, NotConfiguredError, NotFoundError
from foresight.services.events.predicthq import PredictHQLimitError
from foresight.services.events.window import Window, resolve_window
from foresight.services.hotels.city import local_today
from foresight.services.hotels.hotel import get_hotel
from foresight.services.jobs.handlers import HANDLERS, Step
from foresight.services.pricing import model as model_service
from foresight.services.pricing import tuning as tuning_service

FIRST_REFRESH_DAYS = 7
_QUOTA_ERRORS = (PredictHQLimitError,)


async def start_events_job(
    session: AsyncSession,
    hotel_id: int,
    *,
    start: date | None,
    end: date | None,
    scheduled: bool = False,
) -> Job:
    """Queues an events job.

    Every `start_*` checks up front, so a bad request fails with a 4xx
    instead of a queued job that fails later. The worker runs a job through
    `run`, committing at every step its handler yields.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        start (date | None): First night of a backfill.
        end (date | None): Last night of a backfill. With neither date, the
            job fetches upcoming events PredictHQ revised since the last
            such run, or in the last week the first time.
        scheduled (bool): Whether the scheduler started it.

    Returns:
        Job: The queued job.

    Raises:
        NotFoundError: Unknown hotel.
        NotConfiguredError: PREDICTHQ_TOKEN isn't set.
        InvalidWindowError: The window doesn't resolve.
        ConflictError: An events job is already queued or running.
    """
    hotel = await get_hotel(session, hotel_id)
    if not settings.predicthq_token:
        raise NotConfiguredError("PREDICTHQ_TOKEN not set on the server")
    if start is None and end is None:
        since = await job_repo.last_succeeded_start(
            session, hotel_id=hotel.id, kind=JobKind.EVENTS, params={"mode": "recent"}
        ) or _now() - timedelta(days=FIRST_REFRESH_DAYS)
        params = {"mode": "recent", "updated_since": since.isoformat()}
    else:
        window = await resolve_window(
            session, hotel.id, start, end, today=local_today(hotel.city)
        )
        params = {"mode": "window", **window.as_params()}
    params["scheduled"] = scheduled
    return await _queue(session, hotel, JobKind.EVENTS, params)


async def start_file_jobs(
    session: AsyncSession, hotel_id: int, *, files: Sequence[tuple[str, bytes]]
) -> list[tuple[Job, file_ingest.ParsedFile]]:
    """Queues one job per uploaded file, in upload order.

    Every file is recognised and parsed first, so one bad file queues
    nothing.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        files (Sequence[tuple[str, bytes]]): Each file's name and content.

    Returns:
        list[tuple[Job, file_ingest.ParsedFile]]: Each job with its parsed
            file, which the caller hands to the worker.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: A file matches no report, more than one, or
            doesn't parse.
    """
    hotel = await get_hotel(session, hotel_id)
    parsed = file_ingest.parse_files(files)
    return [(await _queue(session, hotel, f.report.kind, f.params), f) for f in parsed]


async def start_train_job(
    session: AsyncSession,
    hotel_id: int,
    *,
    description: str | None,
    start: date | None,
    end: date | None,
    activate: bool,
    ebm_params: dict[str, Any],
    scheduled: bool = False,
) -> Job:
    """Queues a job training a new version on what's already ingested.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        description (str | None): What this version tries.
        start (date | None): First night to train on; None for the first.
        end (date | None): Last night to train on; None for the last.
        activate (bool): Whether the version starts serving.
        ebm_params (dict[str, Any]): Settings passed through to the EBM.
        scheduled (bool): Whether the scheduler started it.

    Returns:
        Job: The queued job.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: Nothing to train on, or start after end.
        ConflictError: A training job is already queued or running.
    """
    hotel = await model_service.check_trainable(session, hotel_id, start=start, end=end)
    params = {
        "description": description,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "activate": activate,
        "ebm_params": ebm_params,
        "scheduled": scheduled,
    }
    return await _queue(session, hotel, JobKind.TRAIN, params)


async def start_tune_job(
    session: AsyncSession, hotel_id: int, *, activate: bool
) -> Job:
    """Queues a job correcting the active model with the manager's rates.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        activate (bool): Whether the tune-up starts serving.

    Returns:
        Job: The queued job.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: The hotel has no active model.
        ConflictError: A tune-up is already queued or running.
    """
    hotel = await tuning_service.check_tunable(session, hotel_id)
    return await _queue(session, hotel, JobKind.TUNE, {"activate": activate})


async def get_job(session: AsyncSession, job_id: int) -> Job:
    """Gets a job.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.

    Returns:
        Job: The job.

    Raises:
        NotFoundError: The job doesn't exist.
    """
    job = await job_repo.get_job(session, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)
    return job


async def list_jobs(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[Job], int]:
    """Lists a hotel's jobs, newest first.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        limit (int): Page size.
        offset (int): Rows to skip.

    Returns:
        tuple[Sequence[Job], int]: The page, and the total.

    Raises:
        NotFoundError: The hotel doesn't exist.
    """
    await get_hotel(session, hotel_id)
    return await job_repo.list_jobs(session, hotel_id, limit=limit, offset=offset)


async def cancel_job(session: AsyncSession, job_id: int) -> Job:
    """Takes a queued job out of the queue.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.

    Returns:
        Job: The cancelled job.

    Raises:
        NotFoundError: Unknown job.
        ConflictError: The job is running or finished.
    """
    if not await job_repo.cancel_queued_job(session, job_id):
        job = await get_job(session, job_id)
        raise ConflictError(
            f"job {job.id} is {job.status.value}; only a queued job can be cancelled"
        )
    return await get_job(session, job_id)


async def _queue(
    session: AsyncSession, hotel: Hotel, kind: JobKind, params: dict[str, Any]
) -> Job:
    """Queues a job, unless one of its kind is already unfinished.

    Uploads stack up in the queue; a second events, training or tune-up run
    would only repeat the first, and spend API credits or training time.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        kind (JobKind): The job.
        params (dict[str, Any]): Its params.

    Returns:
        Job: The queued job.

    Raises:
        ConflictError: A job of this kind is already queued or running.
    """
    if kind not in file_ingest.FILE_KINDS:
        running = await job_repo.find_unfinished_job(
            session, hotel_id=hotel.id, kind=kind
        )
        if running is not None:
            raise ConflictError(
                f"job {running.id} ({kind.value}) is already {running.status.value}"
            )
    return await job_repo.create_job(
        session, hotel_id=hotel.id, kind=kind, params=params
    )


async def run(
    session: AsyncSession, job: Job, payload: Any = None
) -> AsyncIterator[Step]:
    """Runs the job's handler, yielding after each saved chunk.

    Args:
        session (AsyncSession): The database session.
        job (Job): The job.
        payload (Any): What the request handed over in memory, e.g. a parsed
            file.

    Yields:
        Step: After each saved chunk.
    """
    hotel = await get_hotel(session, job.hotel_id)
    async for step in HANDLERS[job.kind](session, hotel, job.params, payload):
        yield step


def initial_resume_from(job: Job) -> date | None:
    """Says where to pick up if the job ends before its first chunk is saved.

    Args:
        job (Job): The job.

    Returns:
        date | None: A backfill's `end`; None for any other job.
    """
    if job.params.get("mode") != "window":
        return None
    return Window.from_params(job.params).end


async def mark_running(session: AsyncSession, job_id: int) -> bool:
    """Starts a queued job.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.

    Returns:
        bool: False if it's no longer queued, e.g. cancelled.
    """
    return await job_repo.start_queued_job(session, job_id, started_at=_now())


async def record_progress(
    session: AsyncSession, job_id: int, progress: dict[str, Any]
) -> None:
    """Records a job's progress.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.
        progress (dict[str, Any]): Its counts so far.
    """
    await job_repo.update_job(session, job_id, progress=progress)


async def mark_succeeded(session: AsyncSession, job_id: int) -> None:
    """Marks a job succeeded.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.
    """
    await job_repo.update_job(
        session,
        job_id,
        status=JobStatus.SUCCEEDED,
        resume_from=None,
        finished_at=_now(),
    )


async def mark_ended_early(
    session: AsyncSession, job_id: int, exc: Exception, resume_from: date | None
) -> None:
    """Marks a job that ended early: stopped on a quota, else failed.

    Either way the saved chunks stay.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.
        exc (Exception): Why it ended.
        resume_from (date | None): Where to pick up.
    """
    stopped = isinstance(exc, _QUOTA_ERRORS)
    await job_repo.update_job(
        session,
        job_id,
        status=JobStatus.STOPPED if stopped else JobStatus.FAILED,
        error=str(exc) if stopped else f"{type(exc).__name__}: {exc}",
        resume_from=resume_from,
        finished_at=_now(),
    )


async def fail_interrupted_jobs(session: AsyncSession) -> int:
    """Fails the jobs a restart left queued or running; they can't continue.

    Args:
        session (AsyncSession): The database session.

    Returns:
        int: How many were failed.
    """
    return await job_repo.fail_unfinished_jobs(
        session, "interrupted by a server restart; start it again"
    )


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Helpers                          │
#          ╰──────────────────────────────────────────────────────────╯


def _now() -> datetime:
    """Gives the current time.

    Returns:
        datetime: Now, in UTC.
    """
    return datetime.now(UTC)
