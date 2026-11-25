from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from pydantic import Field

from foresight import worker
from foresight.database.enums import JobKind, JobStatus
from foresight.routes.access import HotelId, JobId
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services.jobs import freshness as freshness_service
from foresight.services.jobs import job as job_service

router = APIRouter(tags=["Jobs"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class JobResponse(ResponseSchema):
    """A background job: its status, progress and resume point."""

    id: int = Field(description="The job's id; poll GET /jobs/{id}")
    hotel_id: int = Field(description="The hotel it runs for")
    kind: JobKind = Field(description="What the job does")
    status: JobStatus = Field(
        description="queued → running → succeeded, or stopped (a quota) or "
        "failed; a queued job can instead be cancelled"
    )
    params: dict[str, Any] = Field(description="Inputs, as resolved when queued")
    progress: dict[str, Any] = Field(description="Counts so far; matches what's saved")
    error: str | None = Field(description="Why it stopped or failed; null otherwise")
    resume_from: date | None = Field(
        description="Set when a backfill ended early: send it as `end`, with "
        "the same `start`; backfills walk newest first"
    )
    created_at: datetime = Field(description="When it was queued, UTC")
    started_at: datetime | None = Field(
        description="When it began, UTC; null if queued"
    )
    finished_at: datetime | None = Field(
        description="When it ended, UTC; null while unfinished"
    )


class KindFreshnessResponse(ResponseSchema):
    """When one kind of data last refreshed."""

    last_success: datetime | None = Field(
        description="When it last succeeded, UTC; null if it never has"
    )
    last_failure: datetime | None = Field(
        description="When the latest attempt failed or stopped, UTC; null if "
        "the latest attempt succeeded or it never ran"
    )
    error: str | None = Field(description="Why the latest attempt failed; null if not")


class FreshnessResponse(ResponseSchema):
    """When each kind of a hotel's data last refreshed."""

    events: KindFreshnessResponse = Field(description="Routine events refresh")
    hotel_data: KindFreshnessResponse = Field(
        description="Daily New Reservations upload (CSV)"
    )
    training: KindFreshnessResponse = Field(description="Pricing model training")
    recommendations: KindFreshnessResponse = Field(
        description="When a recommended rate last changed (its newest snapshot). "
        "A rate whose inputs hold isn't stored again, so this can be older than "
        "the last request; `last_failure` is always null"
    )


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: JobId, session: SessionDep) -> JobResponse:
    """One job's status, progress and resume point.

    Each hotel's jobs run one at a time, oldest first; poll this for status
    and progress. If a job stops or fails part-way, `resume_from` says where
    to pick up: send it to the same ingest endpoint as `end`, with the same
    `start`. A file job that ends early is finished by uploading the file
    again.

    \f
    Args:
        job_id (JobId): The job.
        session (SessionDep): The database session.

    Returns:
        JobResponse: The job.

    Raises:
        NotFoundError: The job doesn't exist.
    """
    return JobResponse.model_validate(await job_service.get_job(session, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: JobId, session: SessionDep, tasks: BackgroundTasks
) -> JobResponse:
    """Take a queued job out of its hotel's queue.

    A running or finished job can't be cancelled (409).

    \f
    Args:
        job_id (JobId): The job.
        session (SessionDep): The database session.
        tasks (BackgroundTasks): Drops it from the worker's queue.

    Returns:
        JobResponse: The cancelled job.

    Raises:
        ConflictError: The job is running or finished.
    """
    job = await job_service.cancel_job(session, job_id)
    tasks.add_task(worker.discard, job.id)
    return JobResponse.model_validate(job)


@router.get("/hotels/{hotel_id}/jobs", response_model=PageResponse[JobResponse])
async def list_jobs(
    hotel_id: HotelId, session: SessionDep, page: PageDep
) -> PageResponse[JobResponse]:
    """The hotel's jobs, newest first.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        session (SessionDep): The database session.
        page (PageDep): Which page.

    Returns:
        PageResponse[JobResponse]: The page.
    """
    jobs, total = await job_service.list_jobs(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    return paginate(JobResponse, jobs, total, page)


@router.get("/hotels/{hotel_id}/freshness", response_model=FreshnessResponse)
async def get_freshness(hotel_id: HotelId, session: SessionDep) -> FreshnessResponse:
    """When each kind of data last refreshed, and whether the latest attempt failed.

    Events count routine refreshes only, not backfills.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        session (SessionDep): The database session.

    Returns:
        FreshnessResponse: Each kind's latest success and failure.
    """
    result = await freshness_service.get_freshness(session, hotel_id)
    return FreshnessResponse.model_validate(result)
