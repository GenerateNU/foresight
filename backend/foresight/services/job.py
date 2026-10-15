"""Background jobs: one kind per signal, and the job lifecycle.

`start_*` validates up front (the API key is set, the window resolves, the
files parse) so a bad request fails with 4xx instead of a queued job that
fails later. Handlers are async generators: they save through
`services/ingest/` and yield a `Step` after each chunk. The worker
(`foresight/worker.py`) commits at every step, so a job's progress always
matches what is saved, and records the last step's `resume_from` if the run
ends early.

Dates: with neither `start` nor `end` a job does its signal's routine refresh;
with either it backfills the window `services/ingest/window.py` resolves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as date_cls
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from foresight.config import settings
from foresight.database.enums import JobKind, JobStatus
from foresight.repository import job as job_repo
from foresight.services.adapters.open_meteo import FORECAST_DAYS
from foresight.services.adapters.predicthq import PredictHQLimitError
from foresight.services.domain import pricing_model as pricing_model_service
from foresight.services.domain.hotel import get_hotel
from foresight.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotConfiguredError,
    NotFoundError,
)
from foresight.services.ingest import event as event_ingest
from foresight.services.ingest import performance as performance_ingest
from foresight.services.ingest import weather as weather_ingest
from foresight.services.ingest.window import InvalidWindowError, Window, resolve_window

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.city import City
    from foresight.database.models.hotel import Hotel
    from foresight.database.models.job import Job
    from foresight.repository.upsert import Outcome

    type Handler = Callable[
        [AsyncSession, Hotel, Mapping[str, Any], Any], AsyncIterator[Step]
    ]

# How far back the first routine events refresh looks for revisions.
FIRST_REFRESH_DAYS = 7
# A source's quota or rate limit: the job stops rather than fails.
_QUOTA_ERRORS = (PredictHQLimitError,)


@dataclass(frozen=True, slots=True)
class Step:
    """One saved chunk: counts so far, and where to pick up if the run ends
    now (None once nothing is left)."""

    progress: dict[str, Any]
    resume_from: date | None


# --- starting and reading jobs ----------------------------------------------


async def start_weather_job(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> Job:
    """No dates: the next 16 days of forecast. Dates: recorded weather for the
    past part of the window and forecast for the next 16 days of it.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidWindowError: The window doesn't resolve, or lies wholly beyond
            the forecast.
        ConflictError: A weather job is already queued or running.
    """
    hotel = await get_hotel(session, hotel_id)
    params: dict[str, Any] = {"mode": "forecast"}
    if start is not None or end is not None:
        today = _today(hotel.city)
        window = await resolve_window(session, hotel.id, start, end, today=today)
        if window.start > _forecast_end(today):
            raise InvalidWindowError(
                f"the forecast reaches {_forecast_end(today)}; {window.start} is "
                "beyond it"
            )
        params = {"mode": "window", **window.as_params()}
    return await _queue(session, hotel, JobKind.WEATHER, params)


async def start_events_job(
    session: AsyncSession, hotel_id: int, *, start: date | None, end: date | None
) -> Job:
    """No dates: upcoming events PredictHQ revised since the last such run
    (or the last week, the first time). Dates: every event in the window.

    Raises:
        NotFoundError: Unknown hotel.
        NotConfiguredError: PREDICTHQ_TOKEN isn't set.
        InvalidWindowError: The window doesn't resolve.
        ConflictError: An events job is already queued or running.
    """
    hotel = await get_hotel(session, hotel_id)
    if not settings.predicthq_token:
        raise NotConfiguredError("PREDICTHQ_TOKEN not set on the server")
    if start is None and end is None:
        since = await job_repo.last_succeeded_start(
            session, hotel_id=hotel.id, kind=JobKind.EVENTS, params={"mode": "recent"}
        ) or _now() - timedelta(days=FIRST_REFRESH_DAYS)
        params = {"mode": "recent", "updated_since": since.isoformat()}
    else:
        window = await resolve_window(
            session, hotel.id, start, end, today=_today(hotel.city)
        )
        params = {"mode": "window", **window.as_params()}
    return await _queue(session, hotel, JobKind.EVENTS, params)


async def start_performance_job(
    session: AsyncSession,
    hotel_id: int,
    *,
    files: Sequence[tuple[str, bytes]],
    base_rate: Decimal,
) -> tuple[Job, list[performance_ingest.ParsedFile]]:
    """Parse every file now; the job saves them. Returns the job and the
    parsed files, which the caller hands to the worker.

    Raises:
        NotFoundError: Unknown hotel.
        InvalidRequestError: A file doesn't parse.
        ConflictError: A performance job is already queued or running.
    """
    hotel = await get_hotel(session, hotel_id)
    parsed = performance_ingest.parse_files(list(files))
    params = {"files": [f.name for f in parsed], "base_rate": str(base_rate)}
    return await _queue(session, hotel, JobKind.PERFORMANCE, params), parsed


async def start_train_job(
    session: AsyncSession,
    hotel_id: int,
    *,
    description: str | None,
    start: date | None,
    end: date | None,
    activate: bool,
    ebm_params: dict[str, Any],
    copy_settings_from: int | None,
) -> Job:
    """Train a new model version on what's already ingested.

    `copy_settings_from` reuses an earlier version's EBM settings and window;
    anything sent explicitly overrides them.

    Raises:
        NotFoundError: Unknown hotel, or unknown model to copy from.
        InvalidRequestError: Nothing to train on, start after end, or the
            model to copy from belongs to another hotel.
        ConflictError: A training job is already queued or running.
    """
    if copy_settings_from is not None:
        base = await pricing_model_service.get_model(session, copy_settings_from)
        if base.hotel_id != hotel_id:
            raise InvalidRequestError(
                f"model {base.id} belongs to hotel {base.hotel_id}, not {hotel_id}"
            )
        summary = base.training_summary or {}
        ebm_params = {**summary.get("ebm_params", {}), **ebm_params}
        window = summary.get("window", {})
        start = start or _date_or_none(window.get("start"))
        end = end or _date_or_none(window.get("end"))
    hotel = await pricing_model_service.check_trainable(
        session, hotel_id, start=start, end=end
    )
    params = {
        "description": description,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "activate": activate,
        "ebm_params": ebm_params,
        "copy_settings_from": copy_settings_from,
    }
    return await _queue(session, hotel, JobKind.TRAIN, params)


async def get_job(session: AsyncSession, job_id: int) -> Job:
    """Raises NotFoundError for an unknown job."""
    job = await job_repo.get_job(session, job_id)
    if job is None:
        raise NotFoundError("Job", job_id)
    return job


async def list_jobs(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[Job], int]:
    await get_hotel(session, hotel_id)
    return await job_repo.list_jobs(session, hotel_id, limit=limit, offset=offset)


async def _queue(
    session: AsyncSession, hotel: Hotel, kind: JobKind, params: dict[str, Any]
) -> Job:
    running = await job_repo.find_unfinished_job(session, hotel_id=hotel.id, kind=kind)
    if running is not None:
        raise ConflictError(
            f"job {running.id} ({kind.value}) is already {running.status.value}"
        )
    return await job_repo.create_job(
        session, hotel_id=hotel.id, kind=kind, params=params
    )


# --- lifecycle (called by the worker) ---------------------------------------


async def run(
    session: AsyncSession, job: Job, payload: Any = None
) -> AsyncIterator[Step]:
    """Run the job's handler, yielding after each saved chunk.

    `payload` is whatever the request handed over in memory (parsed files).
    """
    hotel = await get_hotel(session, job.hotel_id)
    async for step in _HANDLERS[job.kind](session, hotel, job.params, payload):
        yield step


def initial_resume_from(job: Job) -> date | None:
    """Where to pick up if the job ends before its first chunk is saved."""
    if job.params.get("mode") != "window":
        return None
    window = Window.from_params(job.params)
    return window.end if window.backwards else window.start


async def mark_running(session: AsyncSession, job_id: int) -> None:
    await job_repo.update_job(
        session, job_id, status=JobStatus.RUNNING, started_at=_now()
    )


async def record_progress(
    session: AsyncSession, job_id: int, progress: dict[str, Any]
) -> None:
    await job_repo.update_job(session, job_id, progress=progress)


async def mark_succeeded(session: AsyncSession, job_id: int) -> None:
    await job_repo.update_job(
        session,
        job_id,
        status=JobStatus.SUCCEEDED,
        resume_from=None,
        finished_at=_now(),
    )


async def mark_ended_early(
    session: AsyncSession, job_id: int, exc: Exception, resume_from: date | None
) -> None:
    """Stopped on a quota or rate limit, failed on anything else. Either way
    the saved chunks stay and `resume_from` says where to pick up."""
    stopped = isinstance(exc, _QUOTA_ERRORS)
    await job_repo.update_job(
        session,
        job_id,
        status=JobStatus.STOPPED if stopped else JobStatus.FAILED,
        error=str(exc) if stopped else f"{type(exc).__name__}: {exc}",
        resume_from=resume_from,
        finished_at=_now(),
    )


async def fail_interrupted_jobs(session: AsyncSession) -> int:
    """Jobs left queued or running by a restart can't continue; fail them."""
    return await job_repo.fail_unfinished_jobs(
        session, "interrupted by a server restart; start it again"
    )


# --- handlers ---------------------------------------------------------------


async def _weather(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    city = hotel.city
    if params["mode"] == "forecast":
        outcomes = await weather_ingest.ingest_forecast(session, city)
        yield Step({"outcomes": _counts(outcomes)}, None)
        return

    window = Window.from_params(params)
    today = _today(city)
    past = window.clip(window.start, today - timedelta(days=1))
    future = window.clip(today, _forecast_end(today))
    pieces = [
        ("recorded", first, last) for first, last in (past.years() if past else ())
    ]
    if future is not None:
        forecast = ("forecast", future.start, future.end)
        pieces = [forecast, *pieces] if window.backwards else [*pieces, forecast]

    progress: dict[str, Any] = {"saved": [], "outcomes": {}}
    if window.end > _forecast_end(today):
        progress["beyond_forecast"] = [
            max(window.start, _forecast_end(today) + timedelta(days=1)).isoformat(),
            window.end.isoformat(),
        ]
    total: dict[str, int] = {}
    for i, (source, first, last) in enumerate(pieces):
        if source == "recorded":
            outcomes = await weather_ingest.ingest_actuals(
                session, city, start=first, end=last
            )
        else:
            outcomes = await weather_ingest.ingest_forecast(
                session, city, start=first, end=last
            )
        for name, n in _counts(outcomes).items():
            total[name] = total.get(name, 0) + n
        progress = {
            **progress,
            "saved": [
                *progress["saved"],
                [source, first.isoformat(), last.isoformat()],
            ],
            "outcomes": dict(total),
        }
        yield Step(progress, _next_resume(window, pieces, i))


async def _events(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    if params["mode"] == "recent":
        report = await event_ingest.ingest_recent(
            session,
            hotel.city,
            token=settings.predicthq_token,
            updated_since=datetime.fromisoformat(params["updated_since"]),
        )
        yield Step(_event_progress(report, None), None)
        return

    window = Window.from_params(params)
    months = list(window.months())
    async for report, first, last in event_ingest.ingest_window(
        session, hotel.city, window, token=settings.predicthq_token
    ):
        done = months.index((first, last))
        yield Step(
            _event_progress(report, (done + 1, len(months))),
            _next_resume(window, [(None, a, b) for a, b in months], done),
        )


async def _performance(
    session: AsyncSession,
    hotel: Hotel,
    params: Mapping[str, Any],
    parsed: list[performance_ingest.ParsedFile] | None,
) -> AsyncIterator[Step]:
    if parsed is None:
        raise RuntimeError("the uploaded files didn't reach the worker")

    total: dict[str, int] = {}
    for i, parsed_file in enumerate(parsed, start=1):
        outcomes = await performance_ingest.save_file(
            session, hotel, parsed_file, base_rate=Decimal(params["base_rate"])
        )
        for name, n in _counts(outcomes).items():
            total[name] = total.get(name, 0) + n
        yield Step(
            {"files_done": i, "files_total": len(parsed), "outcomes": dict(total)},
            None,
        )


async def _train(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    result = await pricing_model_service.train(
        session,
        hotel,
        description=params["description"],
        start=_date_or_none(params["start"]),
        end=_date_or_none(params["end"]),
        activate=params["activate"],
        params=params["ebm_params"],
    )
    model = result.model
    yield Step(
        {
            "model_id": model.id,
            "version": model.version,
            "activated": result.activated,
            "seconds": result.seconds,
            "nights_used": model.training_summary["nights_used"],
            "metrics": {k: model.metrics[k] for k in ("mae", "mape", "r2", "coverage")},
        },
        None,
    )


_HANDLERS: dict[JobKind, Handler] = {
    JobKind.WEATHER: _weather,
    JobKind.EVENTS: _events,
    JobKind.PERFORMANCE: _performance,
    JobKind.TRAIN: _train,
}


# --- helpers ----------------------------------------------------------------


def _event_progress(
    report: event_ingest.EventReport, months: tuple[int, int] | None
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "fetched": report.fetched,
        "rejected": report.rejected,
        "outcomes": _counts(report.outcomes),
        "overflowed_months": [
            [a.isoformat(), b.isoformat()] for a, b in report.overflowed
        ],
    }
    if months is not None:
        progress["months_done"], progress["months_total"] = months
    return progress


def _next_resume(
    window: Window, pieces: Sequence[tuple[Any, date, date]], done: int
) -> date | None:
    """Where to pick up once piece `done` is saved: the next piece's start
    (or end, walking backwards), or None when it was the last."""
    if done + 1 >= len(pieces):
        return None
    _, first, last = pieces[done + 1]
    return window.resume_point(first, last)


def _date_or_none(value: str | None) -> date | None:
    return None if value is None else date_cls.fromisoformat(value)


def _forecast_end(today: date) -> date:
    return today + timedelta(days=FORECAST_DAYS - 1)


def _today(city: City) -> date:
    """Today where the city is: stay nights are local."""
    return datetime.now(ZoneInfo(city.timezone)).date()


def _counts(outcomes: Mapping[Outcome, int]) -> dict[str, int]:
    return {outcome.value: n for outcome, n in outcomes.items()}


def _now() -> datetime:
    return datetime.now(UTC)
