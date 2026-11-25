"""What each kind of job does once it runs: one async generator per kind, each
yielding a `Step` after every saved chunk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from foresight.config import settings
from foresight.database.enums import JobKind
from foresight.services.domain import model as model_service
from foresight.services.domain import tuning as tuning_service
from foresight.services.domain.window import Window
from foresight.services.ingest import event as event_ingest
from foresight.services.ingest import files as file_ingest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.repository.upsert import Outcome


@dataclass(frozen=True, slots=True)
class Step:
    """One saved chunk: counts so far, and where to pick up if the run ends
    now (None once nothing is left)."""

    progress: dict[str, Any]
    resume_from: date | None


type Handler = Callable[
    [AsyncSession, Hotel, Mapping[str, Any], Any], AsyncIterator[Step]
]


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
    months = window.months()
    async for report, first, last in event_ingest.ingest_window(
        session, hotel.city, window, token=settings.predicthq_token
    ):
        done = months.index((first, last)) + 1
        # Newest first: pick up with the next, older month as `end`.
        resume = months[done][1] if done < len(months) else None
        yield Step(_event_progress(report, (done, len(months))), resume)


async def _file(
    session: AsyncSession,
    hotel: Hotel,
    _: Mapping[str, Any],
    parsed: file_ingest.ParsedFile | None,
) -> AsyncIterator[Step]:
    """Save an uploaded file's rows a chunk at a time. If it ends early, the
    manager uploads the file again: saving is an upsert."""
    if parsed is None:
        raise RuntimeError("the uploaded file didn't reach the worker")

    total: dict[str, int] = {}
    done = 0
    for chunk in file_ingest.chunks(parsed.rows):
        outcomes = await parsed.report.save(session, hotel, chunk, parsed.extra)
        for name, n in _counts(outcomes).items():
            total[name] = total.get(name, 0) + n
        done += len(chunk)
        progress = {"rows_done": done, "rows_total": len(parsed.rows)}
        yield Step({**progress, "outcomes": dict(total)}, None)


async def _train(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    prepared = await model_service.prepare_training(
        session,
        hotel,
        start=_date_or_none(params["start"]),
        end=_date_or_none(params["end"]),
    )
    # The worker commits at each step, which hands the database connection
    # back while the model fits: a long fit would otherwise outlast it.
    yield Step(
        {
            "stage": "fitting",
            "training_rows": len(prepared.data.rows),
            "target": model_service.TARGET,
        },
        None,
    )
    metrics, artifact = await model_service.fit(prepared, params["ebm_params"])
    result = await model_service.save_version(
        session,
        hotel,
        prepared,
        metrics,
        artifact,
        description=params["description"],
        activate=params["activate"],
    )
    version_row = result.version
    yield Step(
        {
            "model_id": version_row.id,
            "version": version_row.version,
            "activated": result.activated,
            "seconds": result.seconds,
            "training_rows": result.training_rows,
            "training_nights": result.training_nights,
            "target": version_row.metrics.get("target"),
            "feedback_nights": version_row.metrics.get("feedback_nights"),
            "metrics": {
                k: version_row.metrics[k] for k in ("train_seconds", "peak_memory_mb")
            },
        },
        None,
    )


async def _tune(
    session: AsyncSession, hotel: Hotel, params: Mapping[str, Any], _: Any
) -> AsyncIterator[Step]:
    result = await tuning_service.tune(session, hotel, activate=params["activate"])
    version_row = result.version
    yield Step(
        {
            "model_id": None if version_row is None else version_row.id,
            "version": None if version_row is None else version_row.version,
            "activated": result.activated,
            "nights_used": result.nights_used,
            "untouched_used": result.untouched_used,
            "skipped": result.skipped,
            "mean_correction": None
            if version_row is None
            else version_row.metrics["mean_correction"],
        },
        None,
    )


HANDLERS: dict[JobKind, Handler] = {
    JobKind.EVENTS: _events,
    JobKind.RESERVATIONS: _file,
    JobKind.CANCELLATIONS: _file,
    JobKind.TRAIN: _train,
    JobKind.TUNE: _tune,
}


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
        "empty_months": [[a.isoformat(), b.isoformat()] for a, b in report.empty],
    }
    if months is not None:
        progress["months_done"], progress["months_total"] = months
    return progress


def _date_or_none(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _counts(outcomes: Mapping[Outcome, int]) -> dict[str, int]:
    return {outcome.value: n for outcome, n in outcomes.items()}
