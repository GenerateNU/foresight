"""Background jobs: start them, and their lifecycle.

`start_*` validates up front so a bad request fails with 4xx instead of a
queued job that fails later. The worker runs a job through `run` and commits
at every step its handler yields (`services/handlers.py`).
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.config import settings
from foresight.database.enums import JobKind, JobStatus
from foresight.database.models.hotel import Hotel
from foresight.database.models.job import Job
from foresight.repository import job as job_repo
from foresight.services.adapters.predicthq import PredictHQLimitError
from foresight.services.domain import model as model_service
from foresight.services.domain import tuning as tuning_service
from foresight.services.domain.city import local_today
from foresight.services.domain.hotel import get_hotel
from foresight.services.domain.window import Window, resolve_window
from foresight.services.errors import ConflictError, NotConfiguredError, NotFoundError
from foresight.services.handlers import HANDLERS, Step
from foresight.services.ingest import files as file_ingest

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
    """No dates: upcoming events PredictHQ revised since the last such run
    (or the last week, the first time). Dates: every event in the window.
    `scheduled` is for the scheduler's own runs.

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
    """One job per file, in upload order. Every file is recognised and parsed
    first, so one bad file queues nothing. Returns each job with its parsed
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
    """Train a new model version on what's already ingested. `scheduled` is
    for the scheduler's own runs.

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
    """Correct the active model with the manager's rates (decision 0069).

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: The hotel has no active model.
        ConflictError: A tune-up is already queued or running.
    """
    hotel = await tuning_service.check_tunable(session, hotel_id)
    return await _queue(session, hotel, JobKind.TUNE, {"activate": activate})


async def get_job(session: AsyncSession, job_id: int) -> Job:
    """Raises NotFoundError for an unknown job."""
    job = await job_repo.get_job(session, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)
    return job


async def list_jobs(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[Job], int]:
    await get_hotel(session, hotel_id)
    return await job_repo.list_jobs(session, hotel_id, limit=limit, offset=offset)


async def cancel_job(session: AsyncSession, job_id: int) -> Job:
    """Take a queued job out of the queue.

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
    # Uploads stack up in the queue; a second events, training or tune-up
    # run would only repeat the first (and spend API credits or training time).
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
    """Run the job's handler, yielding after each saved chunk.

    `payload` is whatever the request handed over in memory (a parsed file).
    """
    hotel = await get_hotel(session, job.hotel_id)
    async for step in HANDLERS[job.kind](session, hotel, job.params, payload):
        yield step


def initial_resume_from(job: Job) -> date | None:
    """Where to pick up if the job ends before its first chunk is saved."""
    if job.params.get("mode") != "window":
        return None
    return Window.from_params(job.params).end


async def mark_running(session: AsyncSession, job_id: int) -> bool:
    """Start a queued job; False if it is no longer queued (cancelled)."""
    return await job_repo.start_queued_job(session, job_id, started_at=_now())


async def record_progress(
    session: AsyncSession, job_id: int, progress: dict[str, Any]
) -> None:
    await job_repo.update_job(session, job_id, progress=progress)


async def mark_succeeded(session: AsyncSession, job_id: int) -> None:
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
    """Stopped on a quota or rate limit, failed on anything else. Either way
    the saved chunks stay and `resume_from` says where to pick up."""
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
    """Jobs left queued or running by a restart can't continue; fail them."""
    return await job_repo.fail_unfinished_jobs(
        session, "interrupted by a server restart; start it again"
    )


# --- handlers ---------------------------------------------------------------


# --- helpers ----------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _now() -> datetime:
    return datetime.now(UTC)
