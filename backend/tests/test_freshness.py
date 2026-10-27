"""Freshness for a hotel whose jobs are a list in memory (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from foresight.database.enums import JobKind, JobStatus
from foresight.database.models.job import Job
from foresight.services.domain import freshness

NOW = datetime.now(UTC)


def _job(
    status: JobStatus,
    hours_ago: float,
    error: str | None = None,
    params: dict | None = None,
) -> Job:
    return Job(
        kind=JobKind.EVENTS,
        status=status,
        params={"mode": "recent"} if params is None else params,
        finished_at=NOW - timedelta(hours=hours_ago),
        error=error,
    )


async def _events(monkeypatch, jobs: list[Job]) -> freshness.Freshness:
    async def latest(_session, *, kind, params, status=None, **_):
        found = [
            j
            for j in jobs
            if j.kind == kind
            and status in (None, j.status)
            and params.items() <= j.params.items()
        ]
        return max(found, key=lambda j: j.finished_at, default=None)

    monkeypatch.setattr(freshness, "get_hotel", AsyncMock())
    monkeypatch.setattr(freshness.job_repo, "latest_finished_job", latest)
    monkeypatch.setattr(
        freshness.snapshot_repo, "latest_snapshot_at", AsyncMock(return_value=None)
    )
    return (await freshness.get_freshness(None, 1)).events


async def test_never_run(monkeypatch) -> None:
    events = await _events(monkeypatch, [])
    assert events.last_success is None
    assert events.last_failure is None


async def test_succeeded(monkeypatch) -> None:
    events = await _events(monkeypatch, [_job(JobStatus.SUCCEEDED, 2)])
    assert events.last_success is not None
    assert events.last_failure is None


async def test_failed_after_success_shows_both(monkeypatch) -> None:
    jobs = [_job(JobStatus.SUCCEEDED, 30), _job(JobStatus.FAILED, 1, "HTTP 500")]
    events = await _events(monkeypatch, jobs)
    assert events.last_success == jobs[0].finished_at
    assert events.last_failure == jobs[1].finished_at
    assert events.error == "HTTP 500"


async def test_failed_and_never_succeeded(monkeypatch) -> None:
    failed = _job(JobStatus.FAILED, 1, "HTTP 500")
    events = await _events(monkeypatch, [failed])
    assert events.last_success is None
    assert events.last_failure == failed.finished_at
    assert events.error == "HTTP 500"


async def test_success_after_failure_clears_the_failure(monkeypatch) -> None:
    jobs = [_job(JobStatus.FAILED, 5, "HTTP 500"), _job(JobStatus.SUCCEEDED, 1)]
    events = await _events(monkeypatch, jobs)
    assert events.last_success == jobs[1].finished_at
    assert events.last_failure is None  # the latest attempt didn't fail
    assert events.error is None


async def test_backfill_does_not_count_as_a_refresh(monkeypatch) -> None:
    backfill = _job(JobStatus.SUCCEEDED, 1, params={"mode": "window"})
    events = await _events(monkeypatch, [backfill])
    assert events.last_success is None  # only routine refreshes count


async def test_recommendations_report_the_newest_snapshot(monkeypatch) -> None:
    saved_at = NOW - timedelta(hours=3)
    monkeypatch.setattr(freshness, "get_hotel", AsyncMock())
    monkeypatch.setattr(
        freshness.job_repo, "latest_finished_job", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        freshness.snapshot_repo, "latest_snapshot_at", AsyncMock(return_value=saved_at)
    )
    hotel = await freshness.get_freshness(None, 1)
    assert hotel.recommendations.last_success == saved_at
    assert hotel.recommendations.last_failure is None
