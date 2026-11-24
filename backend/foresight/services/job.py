"""Background jobs: one kind per signal or uploaded report, and the lifecycle.

`start_*` validates up front (the API key is set, the window resolves, every
file is recognised and parses) so a bad request fails with 4xx instead of a
queued job that fails later. A hotel's jobs run one at a time, oldest first,
and a queued job can be cancelled. Handlers are async generators: they save
through `services/ingest/` and yield a `Step` after each chunk. The worker
(`foresight/worker.py`) commits at every step, so a job's progress always
matches what is saved, and records the last step's `resume_from` if the run
ends early.

Dates: with neither `start` nor `end` a job does its signal's routine refresh;
with either it backfills the window `services/ingest/window.py` resolves.

`start_due_jobs` queues each hotel's routine refreshes once they're due, for
the worker's scheduler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from datetime import date as date_cls
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from foresight.config import settings
from foresight.database.enums import JobKind, JobStatus
from foresight.repository import job as job_repo
from foresight.services.adapters.predicthq import PredictHQLimitError
from foresight.services.domain import pricing_model as pricing_model_service
from foresight.services.domain import tuning as tuning_service
from foresight.services.domain.city import local_today
from foresight.services.domain.hotel import get_hotel, list_hotels
from foresight.services.errors import (
    ConflictError,
    DomainError,
    NotConfiguredError,
    NotFoundError,
)
from foresight.services.ingest import event as event_ingest
from foresight.services.ingest import files as file_ingest
from foresight.services.ingest.window import Window, resolve_window

if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterator,
        Awaitable,
        Callable,
        Mapping,
        Sequence,
    )
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.database.models.job import Job
    from foresight.repository.upsert import Outcome

    type Handler = Callable[
        [AsyncSession, Hotel, Mapping[str, Any], Any], AsyncIterator[Step]
    ]

log = logging.getLogger(__name__)

# The routine runs once a day at SCHEDULE_HOUR (_due); a scheduled run that
# failed is retried this long after.
RETRY_AFTER = timedelta(hours=1)
# Marks a job the scheduler started. Only these set the next scheduled run, so
# a manual run doesn't move it.
SCHEDULED = {"scheduled": True}
# How far back the first routine events refresh looks for revisions.
FIRST_REFRESH_DAYS = 7
# A source's quota or rate limit: the job stops rather than fails.
_QUOTA_ERRORS = (PredictHQLimitError,)


@dataclass(frozen=True, slots=True)
class Step:
    """One saved chunk: counts so far, and where to pick up if the run ends
    now (None once nothing is left)."""

    progress: dict[str, Any]
    resume_from: date | None


# --- starting and reading jobs ----------------------------------------------


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
    hotel = await pricing_model_service.check_trainable(
        session, hotel_id, start=start, end=end
    )
    params = {
        "description": description,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "activate": activate,
        "ebm_params": ebm_params,
        "scheduled": scheduled,
    }
    return await _queue(session, hotel, JobKind.TRAIN, params)


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
    now = _now()
    for hotel in await list_hotels(session):
        for kind, start in routine:
            if not await _due(session, hotel, kind, now):
                continue
            try:
                queued.append(await start(hotel.id))
            except DomainError as exc:
                log.info("hotel %s: %s not started: %s", hotel.id, kind.value, exc)
    return queued


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


# --- lifecycle (called by the worker) ---------------------------------------


async def run(
    session: AsyncSession, job: Job, payload: Any = None
) -> AsyncIterator[Step]:
    """Run the job's handler, yielding after each saved chunk.

    `payload` is whatever the request handed over in memory (a parsed file).
    """
    hotel = await get_hotel(session, job.hotel_id)
    async for step in _HANDLERS[job.kind](session, hotel, job.params, payload):
        yield step


def initial_resume_from(job: Job) -> date | None:
    """Where to pick up if the job ends before its first chunk is saved."""
    if job.params.get("mode") != "window":
        return None
    window = Window.from_params(job.params)
    return window.end if window.backwards else window.start


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


async def _events(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    if params["mode"] == "recent":
        report = await event_ingest.ingest_recent(
            session,
            hotel.city,
            token=settings.predicthq_token,
            updated_since=datetime.fromisoformat(params["updated_since"]),
        )
        yield Step(_event_progress(report, None), None)
        return

    window = Window.from_params(params)
    months = list(window.months())
    async for report, first, last in event_ingest.ingest_window(
        session, hotel.city, window, token=settings.predicthq_token
    ):
        done = months.index((first, last))
        yield Step(
            _event_progress(report, (done + 1, len(months))),
            _next_resume(window, [(None, a, b) for a, b in months], done),
        )


async def _file(
    session: AsyncSession,
    hotel: Hotel,
    _: Mapping[str, Any],
    parsed: file_ingest.ParsedFile | None,
) -> AsyncIterator[Step]:
    """Save an uploaded file's rows a chunk at a time. If it ends early, the
    manager uploads the file again: saving is an upsert."""
    if parsed is None:
        raise RuntimeError("the uploaded file didn't reach the worker")

    total: dict[str, int] = {}
    done = 0
    for chunk in file_ingest.chunks(parsed.rows):
        outcomes = await parsed.report.save(session, hotel, chunk, parsed.extra)
        for name, n in _counts(outcomes).items():
            total[name] = total.get(name, 0) + n
        done += len(chunk)
        progress = {"rows_done": done, "rows_total": len(parsed.rows)}
        yield Step({**progress, "outcomes": dict(total)}, None)


async def _train(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    prepared = await pricing_model_service.prepare_training(
        session,
        hotel,
        start=_date_or_none(params["start"]),
        end=_date_or_none(params["end"]),
    )
    # The worker commits at each step, which hands the database connection
    # back while the model fits: a long fit would otherwise outlast it.
    yield Step(
        {
            "stage": "fitting",
            "training_rows": len(prepared.data.nights),
            "target": pricing_model_service.TARGET,
        },
        None,
    )
    metrics, artifact = await pricing_model_service.fit(prepared, params["ebm_params"])
    result = await pricing_model_service.save_version(
        session,
        hotel,
        prepared,
        metrics,
        artifact,
        description=params["description"],
        activate=params["activate"],
    )
    model = result.model
    yield Step(
        {
            "model_id": model.id,
            "version": model.version,
            "activated": result.activated,
            "seconds": result.seconds,
            "training_rows": result.training_rows,
            "training_nights": result.training_nights,
            "target": model.metrics.get("target"),
            "feedback_used": result.feedback_used,
            "metrics": {
                k: model.metrics[k] for k in ("train_seconds", "peak_memory_mb")
            },
        },
        None,
    )


async def _tune(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    result = await tuning_service.tune(session, hotel, activate=params["activate"])
    model = result.model
    yield Step(
        {
            "model_id": None if model is None else model.id,
            "version": None if model is None else model.version,
            "activated": result.activated,
            "nights_used": result.nights_used,
            "untouched_used": result.untouched_used,
            "skipped": result.skipped,
            "mean_correction": None
            if model is None
            else model.metrics["mean_correction"],
        },
        None,
    )


_HANDLERS: dict[JobKind, Handler] = {
    JobKind.EVENTS: _events,
    JobKind.RESERVATIONS: _file,
    JobKind.CANCELLATIONS: _file,
    JobKind.TRAIN: _train,
    JobKind.TUNE: _tune,
}


# --- helpers ----------------------------------------------------------------


def _event_progress(
    report: event_ingest.EventReport, months: tuple[int, int] | None
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "fetched": report.fetched,
        "rejected": report.rejected,
        "outcomes": _counts(report.outcomes),
        "overflowed_months": [
            [a.isoformat(), b.isoformat()] for a, b in report.overflowed
        ],
        "empty_months": [[a.isoformat(), b.isoformat()] for a, b in report.empty],
    }
    if months is not None:
        progress["months_done"], progress["months_total"] = months
    return progress


def _next_resume(
    window: Window, pieces: Sequence[tuple[Any, date, date]], done: int
) -> date | None:
    """Where to pick up once piece `done` is saved: the next piece's start
    (or end, walking backwards), or None when it was the last."""
    if done + 1 >= len(pieces):
        return None
    _, first, last = pieces[done + 1]
    return window.resume_point(first, last)


def _date_or_none(value: str | None) -> date | None:
    return None if value is None else date_cls.fromisoformat(value)


def _counts(outcomes: Mapping[Outcome, int]) -> dict[str, int]:
    return {outcome.value: n for outcome, n in outcomes.items()}


def _now() -> datetime:
    return datetime.now(UTC)
