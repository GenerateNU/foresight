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
from foresight.services.jobs import job as job_service

router = APIRouter(tags=["Ingest"])


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯

_DATE_HELP = "YYYY-MM-DD, local to the hotel's city"


class IngestRequest(RequestSchema):
    """Both dates are optional. Leave both out for the routine refresh."""

    start: date | None = Field(
        default=None,
        description=f"First day, inclusive. {_DATE_HELP}. Omit for the hotel's "
        "first booked night",
        examples=["2025-01-01"],
    )
    end: date | None = Field(
        default=None,
        description=f"Last day, inclusive. {_DATE_HELP}. Omit for today",
        examples=["2025-12-31"],
    )


_FULL = example_body(IngestRequest)
_DATE_EXAMPLES: dict[str, Any] = {
    "window": {
        "summary": "Backfill a window",
        "description": "Walks newest month first.",
        "value": _FULL,
    },
    "start_only": {
        "summary": "Backfill from a date to today",
        "value": {"start": _FULL["start"]},
    },
    "refresh": {
        "summary": "Routine refresh (no dates)",
        "description": "Send no body, or {}: what PredictHQ revised since the "
        "last refresh.",
        "value": {},
    },
}

IngestBody = Annotated[IngestRequest | None, Body(openapi_examples=_DATE_EXAMPLES)]

_ACCEPTED = {"status_code": status.HTTP_202_ACCEPTED, "response_model": JobResponse}


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.post("/hotels/{hotel_id}/ingest/events", **_ACCEPTED)
async def ingest_events(
    hotel_id: HotelId,
    session: SessionDep,
    tasks: BackgroundTasks,
    data: IngestBody = None,
) -> JobResponse:
    """PredictHQ events within 10km of the city centre.

    No dates: upcoming events revised since the last such run (the last week,
    the first time). Dates: every event in the window, a month at a time,
    newest first; `end` defaults to today and `start` to the hotel's first
    booked night. Returns 202 with the job, which joins the back of the
    hotel's queue; poll `GET /jobs/{id}`. If it stops part-way, send its
    `resume_from` as `end` again, with the same `start`.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        session (SessionDep): The database session.
        tasks (BackgroundTasks): Queues the job after the response.
        data (IngestBody): The window; none for the routine refresh.

    Returns:
        JobResponse: The queued job.

    Raises:
        NotConfiguredError: PREDICTHQ_TOKEN isn't set.
        InvalidWindowError: The window doesn't resolve.
        ConflictError: An events job is already queued or running.
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
            description="Guestline CSV exports: Daily New Reservations or "
            "Cancellations, in any mix. Each file's report is recognised from "
            "its header"
        ),
    ],
) -> list[JobResponse]:
    """Queue one job per file, in upload order, behind the hotel's other jobs.

    Every file is recognised and parsed before anything is queued, so a file
    that matches no report, matches more than one, or doesn't parse is a 422
    naming it, and nothing is queued. Re-uploading a file changes nothing.

    \f
    Args:
        hotel_id (HotelId): The hotel.
        session (SessionDep): The database session.
        tasks (BackgroundTasks): Queues the jobs after the response, once the
            session has committed them.
        files (list[UploadFile]): The Guestline exports.

    Returns:
        list[JobResponse]: One queued job per file.

    Raises:
        HTTPException: 413 for too many files, or a file over the size limit.
        InvalidRequestError: A file matches no report, more than one, or
            doesn't parse.
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
    for job, parsed in queued:
        tasks.add_task(worker.enqueue, job.id, job.hotel_id, parsed)
    return [JobResponse.model_validate(job) for job, _ in queued]


async def _read_capped(upload: UploadFile) -> bytes:
    """Reads an uploaded file, up to the size limit.

    Args:
        upload (UploadFile): The file.

    Returns:
        bytes: Its content.

    Raises:
        HTTPException: 413 if it's over the limit.
    """
    limit = settings.upload_max_file_mb * 1024 * 1024
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"{upload.filename} is over {settings.upload_max_file_mb} MB",
        )
    return content
