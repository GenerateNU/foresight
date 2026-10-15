"""Jobs: read the background jobs that ingest queues (routes/ingest.py).

Poll `GET /jobs/{id}` for status and progress. If a job stops or fails
part-way, `resume_from` says where to pick up: send it to the same ingest
endpoint as `start` again (or as `end` for a run walking backwards).
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
