"""Jobs: read the background jobs that ingest queues (routes/ingest.py).

Poll `GET /jobs/{id}` for status and progress. If a job stops or fails
part-way, `resume_from` says where to pick up: send it to the same ingest
endpoint as `start` again (or as `end` for a run walking backwards).

`GET /hotels/{id}/freshness` reads the same jobs to say when each kind of data
last refreshed and whether it's stale.
"""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path
from pydantic import Field

from foresight.database.enums import JobKind, JobStatus
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services import job as job_service
from foresight.services.domain import freshness as freshness_service

router = APIRouter(tags=["Jobs"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class JobResponse(ResponseSchema):
    id: int = Field(description="The job's id; poll GET /jobs/{id}")
    hotel_id: int = Field(description="The hotel it runs for")
    kind: JobKind = Field(description="What the job does")
    status: JobStatus = Field(
        description="queued → running → succeeded, or stopped (a quota) or failed"
    )
    params: dict[str, Any] = Field(description="Inputs, as resolved when queued")
    progress: dict[str, Any] = Field(description="Counts so far; matches what's saved")
    error: str | None = Field(description="Why it stopped or failed; null otherwise")
    resume_from: date | None = Field(
        description="Set when the run ended early: send it as `start` again, or "
        "as `end` if the run was walking backwards"
    )
    created_at: datetime = Field(description="When it was queued, UTC")
    started_at: datetime | None = Field(
        description="When it began, UTC; null if queued"
    )
    finished_at: datetime | None = Field(
        description="When it ended, UTC; null while unfinished"
    )


class KindFreshnessResponse(ResponseSchema):
    last_success: datetime | None = Field(
        description="When it last succeeded, UTC; null if it never has"
    )
    last_failure: datetime | None = Field(
        description="When the latest attempt failed or stopped, UTC; null if "
        "the latest attempt succeeded or it never ran"
    )
    error: str | None = Field(description="Why the latest attempt failed; null if not")
    stale: bool = Field(
        description="Never succeeded, or the last success is too old: 1 day for "
        "events and weather, 7 for hotel data, 30 for training"
    )


class FreshnessResponse(ResponseSchema):
    events: KindFreshnessResponse = Field(description="Routine events refresh")
    weather: KindFreshnessResponse = Field(description="Routine forecast refresh")
    hotel_data: KindFreshnessResponse = Field(description="Hotel data upload (CSV)")
    training: KindFreshnessResponse = Field(description="Pricing model training")
    recommendations: KindFreshnessResponse | None = Field(
        description="Recommendation snapshots; always null until they're stored"
    )


JobId = Annotated[int, Path(description="The job's id", examples=[1])]
HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: JobId, session: SessionDep) -> JobResponse:
    """One job's status, progress and resume point."""
    return JobResponse.model_validate(await job_service.get_job(session, job_id))


@router.get("/hotels/{hotel_id}/jobs", response_model=PageResponse[JobResponse])
async def list_jobs(
    hotel_id: HotelId, session: SessionDep, page: PageDep
) -> PageResponse[JobResponse]:
    """The hotel's jobs, newest first."""
    jobs, total = await job_service.list_jobs(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    return paginate(JobResponse, jobs, total, page)


@router.get("/hotels/{hotel_id}/freshness", response_model=FreshnessResponse)
async def get_freshness(hotel_id: HotelId, session: SessionDep) -> FreshnessResponse:
    """When each kind of data last refreshed, and whether it's stale."""
    result = await freshness_service.get_freshness(session, hotel_id)
    return FreshnessResponse.model_validate(result)
