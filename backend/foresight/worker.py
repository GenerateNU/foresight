"""Runs background jobs started through the API, one hotel queue at a time.

Each hotel has one in-memory queue (decision 0052). Jobs of every kind join it
in the order they were queued and run one at a time; different hotels' queues
run side by side. A request queues a job with `tasks.add_task(enqueue, ...)`,
so the job joins only after the request has committed its row. A job that is
no longer `queued` when its turn comes (it was cancelled) is skipped.

The one place besides `database.session.get_session` that opens a session and
commits. A job outlives the request that queued it, and it commits after every
chunk so a run that ends early keeps its finished work and records where to
resume. Everything it does goes through `services/job.py`.

The queues live in the API process, so production runs a single uvicorn
worker. A restart loses them; on startup `fail_interrupted_jobs` marks jobs
left queued or running failed so they can be started again.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from foresight.database.session import async_session_factory
from foresight.services import job as job_service

log = logging.getLogger(__name__)

# hotel id → job ids waiting, oldest first
_queues: dict[int, deque[int]] = {}
# hotel id → the task working through its queue, while there is one
_runners: dict[int, asyncio.Task[None]] = {}
# job id → in-memory input a request handed over (a parsed file)
_payloads: dict[int, Any] = {}


async def enqueue(job_id: int, hotel_id: int, payload: Any = None) -> None:
    """Add a committed job to the back of its hotel's queue. Async so FastAPI
    runs it on the event loop rather than in a thread."""
    if payload is not None:
        _payloads[job_id] = payload
    _queues.setdefault(hotel_id, deque()).append(job_id)
    if hotel_id not in _runners:
        _runners[hotel_id] = asyncio.create_task(_drain(hotel_id))


async def discard(job_id: int) -> None:
    """Drop a cancelled job's in-memory input. Its id stays in the queue and
    is skipped when reached."""
    _payloads.pop(job_id, None)


async def _drain(hotel_id: int) -> None:
    queue = _queues[hotel_id]
    try:
        while queue:
            job_id = queue.popleft()
            try:
                await run_job(job_id, _payloads.pop(job_id, None))
            except Exception:
                # run_job records its own failures; this is the bookkeeping
                # around it failing (the database down). Keep the queue moving.
                log.exception("job %s could not be run", job_id)
    finally:
        # No await between the empty check and here, so an enqueue can't slip
        # in unseen: it either lands before the check or starts a new runner.
        del _runners[hotel_id]
        if not queue:
            del _queues[hotel_id]


async def run_job(job_id: int, payload: Any = None) -> None:
    """`payload` is in-memory input the request handed over (a parsed file)."""
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
    async with async_session_factory() as session:
        count = await job_service.fail_interrupted_jobs(session)
        await session.commit()
    if count:
        log.warning("marked %d interrupted job(s) failed", count)
