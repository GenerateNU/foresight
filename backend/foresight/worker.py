import asyncio
import logging
from collections import deque
from typing import Any

from foresight.database.session import async_session_factory
from foresight.services import job as job_service
from foresight.services import scheduler

log = logging.getLogger(__name__)

SCHEDULE_CHECK_SECONDS = 15 * 60

_queues: dict[int, deque[int]] = {}
_runners: dict[int, asyncio.Task[None]] = {}
_payloads: dict[int, Any] = {}


async def enqueue(job_id: int, hotel_id: int, payload: Any = None) -> None:
    """Adds a committed job to the back of its hotel's queue.

    Each hotel has one in-memory queue: jobs of every kind run one at a time,
    in the order queued, and different hotels' queues run side by side. A
    request queues a job with `tasks.add_task(enqueue, ...)`, so it joins only
    after the request has committed its row. Async, so FastAPI runs it on the
    event loop rather than in a thread.

    The queues live in the API process, so production runs a single uvicorn
    worker, and a restart, deploy or sleep loses them. That's safe on Render's
    free plan, where the old process has stopped before the new one starts; a
    paid plan overlaps them.

    Args:
        job_id (int): The job.
        hotel_id (int): Its hotel.
        payload (Any): In-memory input the request handed over, e.g. a parsed
            file.
    """
    if payload is not None:
        _payloads[job_id] = payload
    _queues.setdefault(hotel_id, deque()).append(job_id)
    if hotel_id not in _runners:
        _runners[hotel_id] = asyncio.create_task(_drain(hotel_id))


async def discard(job_id: int) -> None:
    """Drops a cancelled job's in-memory input.

    Its id stays in the queue and is skipped when reached.

    Args:
        job_id (int): The job.
    """
    _payloads.pop(job_id, None)


async def _drain(hotel_id: int) -> None:
    """Runs a hotel's queued jobs one at a time until the queue is empty.

    A job that can't be run at all, e.g. with the database down, is logged and
    the queue moves on; `run_job` records every other failure itself. Nothing
    awaits between the empty check and removing the runner, so an enqueue
    either lands before the check or starts a new runner.

    Args:
        hotel_id (int): The hotel.
    """
    queue = _queues[hotel_id]
    try:
        while queue:
            job_id = queue.popleft()
            try:
                await run_job(job_id, _payloads.pop(job_id, None))
            except Exception:
                log.exception("job %s could not be run", job_id)
    finally:
        del _runners[hotel_id]
        if not queue:
            del _queues[hotel_id]


async def run_job(job_id: int, payload: Any = None) -> None:
    """Runs one job, committing after every step.

    With `get_session`, the one place that opens a session and commits: a job
    outlives the request that queued it, and committing after every chunk
    means a run that ends early keeps its finished work and records where to
    resume. A job no longer queued, i.e. cancelled, is skipped.

    Args:
        job_id (int): The job.
        payload (Any): In-memory input the request handed over, e.g. a parsed
            file.
    """
    async with async_session_factory() as session:
        started = await job_service.mark_running(session, job_id)
        await session.commit()
        if not started:
            log.info("job %s skipped: no longer queued", job_id)
            return
        job = await job_service.get_job(session, job_id)

        resume_from = job_service.initial_resume_from(job)
        try:
            async for step in job_service.run(session, job, payload):
                await job_service.record_progress(session, job_id, step.progress)
                await session.commit()
                resume_from = step.resume_from
        except Exception as exc:
            log.exception("job %s ended early", job_id)
            await session.rollback()
            await job_service.mark_ended_early(session, job_id, exc, resume_from)
        else:
            await job_service.mark_succeeded(session, job_id)
        await session.commit()


async def fail_interrupted_jobs() -> None:
    """Fails the jobs a restart left queued or running, so they can be started again."""
    async with async_session_factory() as session:
        count = await job_service.fail_interrupted_jobs(session)
        await session.commit()
    if count:
        log.warning("marked %d interrupted job(s) failed", count)


async def schedule_forever() -> None:
    """Queues each hotel's routine jobs once they're due, checking every 15 minutes.

    Runs with SCHEDULER_ENABLED; a failed check is logged and retried at the
    next one.
    """
    while True:
        try:
            async with async_session_factory() as session:
                jobs = await scheduler.start_due_jobs(session)
                await session.commit()
            for job in jobs:
                await enqueue(job.id, job.hotel_id)
        except Exception:
            log.exception("scheduled jobs could not be started")
        await asyncio.sleep(SCHEDULE_CHECK_SECONDS)
