"""Ingest jobs: pull a signal in for a hotel, then poll the job.

Each POST validates and queues a job, returns 202 with it, and runs it after
the response. Poll `GET /jobs/{id}` for status and progress.

Dates (weather and events): send neither for the routine refresh, or either to
backfill a window:

- start and end: that window.
- start only: start to today.
- end only: back from end to the hotel's first loaded night, newest first.

If a job stops or fails part-way, `resume_from` says where to pick up: send it
as `start` again (or as `end` for a run walking backwards).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile, status
from pydantic import Field

from foresight import worker
from foresight.database.enums import JobKind, JobStatus
from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    RequestSchema,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services import job as job_service

router = APIRouter(tags=["jobs"])


# --- schemas ----------------------------------------------------------------


class IngestRequest(RequestSchema):
    start: date | None = Field(default=None, description="First day, inclusive")
    end: date | None = Field(default=None, description="Last day, inclusive")


class JobResponse(ResponseSchema):
    id: int
    hotel_id: int
    kind: JobKind
    status: JobStatus
    params: dict[str, Any] = Field(description="Inputs, as resolved when queued")
    progress: dict[str, Any] = Field(description="Counts so far; matches what's saved")
    error: str | None
    resume_from: date | None = Field(
        description="Set when the run ended early: send it as `start` again, or "
        "as `end` if the run was walking backwards"
    )
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


_ACCEPTED = {"status_code": status.HTTP_202_ACCEPTED, "response_model": JobResponse}


# --- endpoints --------------------------------------------------------------


@router.post("/hotels/{hotel_id}/ingest/weather", **_ACCEPTED)
async def ingest_weather(
    hotel_id: int,
    session: SessionDep,
    tasks: BackgroundTasks,
    data: IngestRequest | None = None,
) -> JobResponse:
    """Open-Meteo weather for the hotel's city.

    No dates: the next 16 days of forecast. Dates: recorded weather for the
    past days in the window, forecast for the next 16; days beyond that have
    no source and are listed in `progress.beyond_forecast`.
    """
    data = data or IngestRequest()
    job = await job_service.start_weather_job(
        session, hotel_id, start=data.start, end=data.end
    )
    # Runs after the response, by which time get_session has committed the row.
    tasks.add_task(worker.run_job, job.id)
    return JobResponse.model_validate(job)


@router.post("/hotels/{hotel_id}/ingest/events", **_ACCEPTED)
async def ingest_events(
    hotel_id: int,
    session: SessionDep,
    tasks: BackgroundTasks,
    data: IngestRequest | None = None,
) -> JobResponse:
    """PredictHQ events within 10km of the city centre.

    No dates: upcoming events revised since the last such run (the last week,
    the first time). Dates: every event in the window, a month at a time.
    """
    data = data or IngestRequest()
    job = await job_service.start_events_job(
        session, hotel_id, start=data.start, end=data.end
    )
    tasks.add_task(worker.run_job, job.id)
    return JobResponse.model_validate(job)


@router.post("/hotels/{hotel_id}/ingest/performance", **_ACCEPTED)
async def ingest_performance(
    hotel_id: int,
    session: SessionDep,
    tasks: BackgroundTasks,
    files: Annotated[
        list[UploadFile], File(description="Client nightly exports (CSV)")
    ],
    base_rate: Annotated[Decimal, Form(gt=0, description="The normal nightly price")],
) -> JobResponse:
    """Load client exports onto the hotel's standard room type, one file per
    step. Every file is parsed before the job is queued, so a bad file is a
    422 and nothing is saved. Re-importing a file changes nothing."""
    contents = [
        (f.filename or f"file {i}", await f.read()) for i, f in enumerate(files)
    ]
    job, parsed = await job_service.start_performance_job(
        session, hotel_id, files=contents, base_rate=base_rate
    )
    tasks.add_task(worker.run_job, job.id, parsed)
    return JobResponse.model_validate(job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, session: SessionDep) -> JobResponse:
    """One job's status, progress and resume point."""
    return JobResponse.model_validate(await job_service.get_job(session, job_id))


@router.get("/hotels/{hotel_id}/jobs", response_model=PageResponse[JobResponse])
async def list_jobs(
    hotel_id: int, session: SessionDep, page: PageDep
) -> PageResponse[JobResponse]:
    """The hotel's jobs, newest first."""
    jobs, total = await job_service.list_jobs(
        session, hotel_id, limit=page.limit, offset=page.offset
    )
    return paginate(JobResponse, jobs, total, page)
