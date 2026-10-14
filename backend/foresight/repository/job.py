"""Data access for `jobs`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update

from foresight.database.enums import JobStatus
from foresight.database.models.job import Job
from foresight.repository.pagination import fetch_page

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.enums import JobKind

_UNFINISHED = (JobStatus.QUEUED, JobStatus.RUNNING)


async def create_job(
    session: AsyncSession, *, hotel_id: int, kind: JobKind, params: dict[str, Any]
) -> Job:
    job = Job(hotel_id=hotel_id, kind=kind, params=params, progress={})
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def list_jobs(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[Job], int]:
    """Newest first."""
    stmt = select(Job).where(Job.hotel_id == hotel_id).order_by(Job.id.desc())
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def update_job(session: AsyncSession, job_id: int, **values: Any) -> None:
    await session.execute(update(Job).where(Job.id == job_id).values(**values))


async def fail_unfinished_jobs(session: AsyncSession, error: str) -> int:
    """Mark every queued or running job failed; returns how many."""
    result = await session.execute(
        update(Job)
        .where(Job.status.in_(_UNFINISHED))
        .values(status=JobStatus.FAILED, error=error, finished_at=func.now())
    )
    return result.rowcount


async def find_unfinished_job(
    session: AsyncSession, *, hotel_id: int, kind: JobKind
) -> Job | None:
    """A queued or running job of this kind for the hotel, if any."""
    return await session.scalar(
        select(Job).where(
            Job.hotel_id == hotel_id,
            Job.kind == kind,
            Job.status.in_(_UNFINISHED),
        )
    )


async def last_succeeded_start(
    session: AsyncSession, *, hotel_id: int, kind: JobKind, params: dict[str, Any]
) -> datetime | None:
    """When the newest succeeded job of this kind whose params contain
    `params` started, if any."""
    return await session.scalar(
        select(func.max(Job.started_at)).where(
            Job.hotel_id == hotel_id,
            Job.kind == kind,
            Job.status == JobStatus.SUCCEEDED,
            Job.params.contains(params),
        )
    )
