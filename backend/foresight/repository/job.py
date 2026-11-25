from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import JobKind, JobStatus
from foresight.database.models.hotel import Hotel
from foresight.database.models.job import Job
from foresight.repository.pagination import fetch_page

_UNFINISHED = (JobStatus.QUEUED, JobStatus.RUNNING)


async def create_job(
    session: AsyncSession, *, hotel_id: int, kind: JobKind, params: dict[str, Any]
) -> Job:
    """Queues a job.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        kind (JobKind): What it does.
        params (dict[str, Any]): Its inputs, as resolved.

    Returns:
        Job: The new job, queued.
    """
    job = Job(hotel_id=hotel_id, kind=kind, params=params, progress={})
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    """Gets a job.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.

    Returns:
        Job | None: The job, or None if it doesn't exist.
    """
    return await session.get(Job, job_id)


async def list_jobs(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[Job], int]:
    """Lists one page of the hotel's jobs, newest first.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        limit (int): Most jobs to return.
        offset (int): Jobs to skip.

    Returns:
        tuple[Sequence[Job], int]: The page, and how many jobs there are.
    """
    stmt = select(Job).where(Job.hotel_id == hotel_id).order_by(Job.id.desc())
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def update_job(session: AsyncSession, job_id: int, **values: Any) -> None:
    """Changes a job's columns.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.
        **values (Any): The columns to change.
    """
    await session.execute(update(Job).where(Job.id == job_id).values(**values))


async def start_queued_job(
    session: AsyncSession, job_id: int, *, started_at: datetime
) -> bool:
    """Marks a queued job running.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.
        started_at (datetime): When it started.

    Returns:
        bool: False if it isn't queued any more.
    """
    result = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
        .values(status=JobStatus.RUNNING, started_at=started_at)
    )
    return result.rowcount == 1


async def cancel_queued_job(session: AsyncSession, job_id: int) -> bool:
    """Marks a queued job cancelled.

    Args:
        session (AsyncSession): The database session.
        job_id (int): The job.

    Returns:
        bool: False if it isn't queued, or doesn't exist.
    """
    result = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
        .values(status=JobStatus.CANCELLED, finished_at=func.now())
    )
    return result.rowcount == 1


async def fail_unfinished_jobs(session: AsyncSession, error: str) -> int:
    """Marks every queued or running job failed.

    Args:
        session (AsyncSession): The database session.
        error (str): Why they failed.

    Returns:
        int: How many jobs were failed.
    """
    result = await session.execute(
        update(Job)
        .where(Job.status.in_(_UNFINISHED))
        .values(status=JobStatus.FAILED, error=error, finished_at=func.now())
    )
    return result.rowcount


async def find_unfinished_job(
    session: AsyncSession, *, hotel_id: int, kind: JobKind
) -> Job | None:
    """Finds a queued or running job of a kind for the hotel.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        kind (JobKind): The kind.

    Returns:
        Job | None: The job, or None if there isn't one.
    """
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
    """Finds when the newest succeeded job of a kind started.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        kind (JobKind): The kind.
        params (dict[str, Any]): Params the job's must contain.

    Returns:
        datetime | None: When it started, or None if none succeeded.
    """
    return await session.scalar(
        select(func.max(Job.started_at)).where(
            Job.hotel_id == hotel_id,
            Job.kind == kind,
            Job.status == JobStatus.SUCCEEDED,
            Job.params.contains(params),
        )
    )


async def latest_finished_job(
    session: AsyncSession,
    *,
    hotel_id: int,
    kind: JobKind,
    params: dict[str, Any],
    status: JobStatus | None = None,
) -> Job | None:
    """Finds the newest finished job of a kind; a cancelled job never ran.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        kind (JobKind): The kind.
        params (dict[str, Any]): Params the job's must contain.
        status (JobStatus | None): Only this status; None for any.

    Returns:
        Job | None: The job, or None if there isn't one.
    """
    stmt = select(Job).where(
        Job.hotel_id == hotel_id,
        Job.kind == kind,
        Job.finished_at.is_not(None),
        Job.status != JobStatus.CANCELLED,
        Job.params.contains(params),
    )
    if status is not None:
        stmt = stmt.where(Job.status == status)
    return await session.scalar(stmt.order_by(Job.finished_at.desc()).limit(1))


async def list_finished_jobs_in_city(
    session: AsyncSession,
    *,
    city_id: int,
    kind: JobKind,
    params: dict[str, Any],
) -> Sequence[Job]:
    """Lists finished jobs of a kind for any hotel in a city, oldest first.

    Args:
        session (AsyncSession): The database session.
        city_id (int): The city.
        kind (JobKind): The kind.
        params (dict[str, Any]): Params the jobs' must contain.

    Returns:
        Sequence[Job]: The jobs.
    """
    result = await session.scalars(
        select(Job)
        .join(Hotel, Job.hotel_id == Hotel.id)
        .where(
            Hotel.city_id == city_id,
            Job.finished_at.is_not(None),
            Job.kind == kind,
            Job.params.contains(params),
        )
        .order_by(Job.id)
    )
    return result.all()
