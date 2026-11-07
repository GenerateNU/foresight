"""Ingest: pull a signal in, or load uploaded files, as background jobs.

Each POST validates and queues its job (one per file for uploads), returns 202,
and the job joins the back of the hotel's queue after the response: a hotel's
jobs run one at a time, oldest first. Poll `GET /jobs/{id}` (routes/job.py)
for status and progress.

Dates (weather and events): send neither for the routine refresh, or either to
backfill a window:

- start and end: that window.
- start only: start to today.
- end only: back from end to the hotel's first loaded night, newest first.

If a job stops or fails part-way, `resume_from` says where to pick up: send it
as `start` again (or as `end` for a run walking backwards).
"""

from datetime import date
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import Field

from foresight import worker
from foresight.config import settings
from foresight.routes.access import HotelId
from foresight.routes.helpers import RequestSchema, SessionDep, example_body
from foresight.routes.job import JobResponse
from foresight.services import job as job_service

router = APIRouter(tags=["Ingest"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

_DATE_HELP = "YYYY-MM-DD, local to the hotel's city"


class IngestRequest(RequestSchema):
    """Both dates are optional. Leave both out for the routine refresh."""

    start: date | None = Field(
        default=None,
        description=f"First day, inclusive. {_DATE_HELP}. Alone: from here to today",
        examples=["2025-01-01"],
    )
    end: date | None = Field(
        default=None,
        description=f"Last day, inclusive. {_DATE_HELP}. Alone: back from here "
        "to the hotel's first loaded night",
        examples=["2025-12-31"],
    )


# One per mode, shown as a picker in /docs. The first is the body built from
# the fields (`example_body`), so it matches the schema; the others are cut
# down from it. The empty refresh body goes last.
_FULL = example_body(IngestRequest)
_DATE_EXAMPLES: dict[str, Any] = {
    "window": {"summary": "Backfill a window", "value": _FULL},
    "start_only": {
        "summary": "Backfill from a date to today",
        "value": {"start": _FULL["start"]},
    },
    "end_only": {
        "summary": "Backfill back to the first loaded night",
        "description": "Needs performance data loaded first; walks newest first.",
        "value": {"end": _FULL["end"]},
    },
    "refresh": {
        "summary": "Routine refresh (no dates)",
        "description": "Send no body, or {}. Weather: the 16-day forecast. "
        "Events: what PredictHQ revised since the last refresh.",
        "value": {},
    },
}

IngestBody = Annotated[IngestRequest | None, Body(openapi_examples=_DATE_EXAMPLES)]

_ACCEPTED = {"status_code": status.HTTP_202_ACCEPTED, "response_model": JobResponse}


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post("/hotels/{hotel_id}/ingest/weather", **_ACCEPTED)
async def ingest_weather(
    hotel_id: HotelId,
    session: SessionDep,
    tasks: BackgroundTasks,
    data: IngestBody = None,
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
    # Queued after the response, by which time get_session has committed the row.
    tasks.add_task(worker.enqueue, job.id, job.hotel_id)
    return JobResponse.model_validate(job)


@router.post("/hotels/{hotel_id}/ingest/events", **_ACCEPTED)
async def ingest_events(
    hotel_id: HotelId,
    session: SessionDep,
    tasks: BackgroundTasks,
    data: IngestBody = None,
) -> JobResponse:
    """PredictHQ events within 10km of the city centre.

    No dates: upcoming events revised since the last such run (the last week,
    the first time). Dates: every event in the window, a month at a time.
    """
    data = data or IngestRequest()
    job = await job_service.start_events_job(
        session, hotel_id, start=data.start, end=data.end
    )
    tasks.add_task(worker.enqueue, job.id, job.hotel_id)
    return JobResponse.model_validate(job)


@router.post(
    "/hotels/{hotel_id}/ingest/files",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=list[JobResponse],
)
async def ingest_files(
    hotel_id: HotelId,
    session: SessionDep,
    tasks: BackgroundTasks,
    files: Annotated[
        list[UploadFile],
        File(
            description="Guestline CSV exports: Actual & Forecast, Daily New "
            "Reservations or Cancellations, in any mix. Each file's report is "
            "recognised from its header"
        ),
    ],
) -> list[JobResponse]:
    """Queue one job per file, in upload order, behind the hotel's other jobs.

    Every file is recognised and parsed before anything is queued, so a file
    that matches no report, matches more than one, or doesn't parse is a 422
    naming it, and nothing is queued. Re-uploading a file changes nothing.
    """
    if len(files) > settings.upload_max_files:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"at most {settings.upload_max_files} files per upload",
        )
    contents = [
        (f.filename or f"file {i}", await _read_capped(f)) for i, f in enumerate(files)
    ]
    queued = await job_service.start_file_jobs(session, hotel_id, files=contents)
    # Added after the response, by which time get_session has committed the rows.
    for job, parsed in queued:
        tasks.add_task(worker.enqueue, job.id, job.hotel_id, parsed)
    return [JobResponse.model_validate(job) for job, _ in queued]


async def _read_capped(upload: UploadFile) -> bytes:
    """The file's bytes; 413 if it is over the size limit."""
    limit = settings.upload_max_file_mb * 1024 * 1024
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"{upload.filename} is over {settings.upload_max_file_mb} MB",
        )
    return content
