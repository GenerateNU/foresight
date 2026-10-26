"""Ingest: pull a signal in for a hotel as a background job.

Each POST validates and queues a job, returns 202 with it, and runs it after
the response. Poll `GET /jobs/{id}` (routes/job.py) for status and progress.

Dates (weather and events): send neither for the routine refresh, or either to
backfill a window:

- start and end: that window.
- start only: start to today.
- end only: back from end to the hotel's first loaded night, newest first.

If a job stops or fails part-way, `resume_from` says where to pick up: send it
as `start` again (or as `end` for a run walking backwards).
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    File,
    Form,
    Path,
    UploadFile,
    status,
)
from pydantic import Field

from foresight import worker
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

HotelId = Annotated[int, Path(description="The hotel's id", examples=[1])]


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
    # Runs after the response, by which time get_session has committed the row.
    tasks.add_task(worker.run_job, job.id)
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
    tasks.add_task(worker.run_job, job.id)
    return JobResponse.model_validate(job)


@router.post("/hotels/{hotel_id}/ingest/performance", **_ACCEPTED)
async def ingest_performance(
    hotel_id: HotelId,
    session: SessionDep,
    tasks: BackgroundTasks,
    files: Annotated[
        list[UploadFile], File(description="Client nightly exports (CSV)")
    ],
    base_rate: Annotated[
        Decimal,
        Form(
            gt=0,
            description="The standard nightly price (rack rate), in EUR. Stored "
            "on the room type; re-importing with a new value replaces it",
            examples=["100.00"],
        ),
    ],
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
