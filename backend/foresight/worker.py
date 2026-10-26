"""Runs background jobs started through the API.

The one place besides `database.session.get_session` that opens a session and
commits. A job outlives the request that queued it, and it commits after every
chunk so a run that ends early keeps its finished work and records where to
resume. Everything it does goes through `services/job.py`.

Jobs run in the API process (FastAPI background tasks), so production runs a
single uvicorn worker. A restart kills running jobs; on startup
`fail_interrupted_jobs` marks those failed so they can be started again.
"""

from __future__ import annotations

import logging
from typing import Any

from foresight.database.session import async_session_factory
from foresight.services import job as job_service

log = logging.getLogger(__name__)


async def run_job(job_id: int, payload: Any = None) -> None:
    """`payload` is in-memory input the request hands over (uploaded files)."""
    async with async_session_factory() as session:
        job = await job_service.get_job(session, job_id)
        await job_service.mark_running(session, job_id)
        await session.commit()

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
