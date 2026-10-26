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
    return (await freshness.get_freshness(None, 1)).events


async def test_never_run(monkeypatch) -> None:
    events = await _events(monkeypatch, [])
    assert events.last_success is None
    assert events.last_failure is None
    assert events.stale


async def test_succeeded(monkeypatch) -> None:
    events = await _events(monkeypatch, [_job(JobStatus.SUCCEEDED, 2)])
    assert events.last_success is not None
    assert events.last_failure is None
    assert not events.stale


async def test_failed_after_success_shows_both(monkeypatch) -> None:
    jobs = [_job(JobStatus.SUCCEEDED, 30), _job(JobStatus.FAILED, 1, "HTTP 500")]
    events = await _events(monkeypatch, jobs)
    assert events.last_success == jobs[0].finished_at
    assert events.last_failure == jobs[1].finished_at
    assert events.error == "HTTP 500"
    assert events.stale  # last success was 30 hours ago


async def test_failed_and_never_succeeded(monkeypatch) -> None:
    failed = _job(JobStatus.FAILED, 1, "HTTP 500")
    events = await _events(monkeypatch, [failed])
    assert events.last_success is None
    assert events.last_failure == failed.finished_at
    assert events.error == "HTTP 500"
    assert events.stale  # never succeeded


async def test_success_after_failure_clears_the_failure(monkeypatch) -> None:
    jobs = [_job(JobStatus.FAILED, 5, "HTTP 500"), _job(JobStatus.SUCCEEDED, 1)]
    events = await _events(monkeypatch, jobs)
    assert events.last_success == jobs[1].finished_at
    assert events.last_failure is None  # the latest attempt didn't fail
    assert events.error is None
    assert not events.stale


async def test_succeeded_but_stale(monkeypatch) -> None:
    old = _job(JobStatus.SUCCEEDED, 25)  # events go stale after 24 hours
    events = await _events(monkeypatch, [old])
    assert events.last_success == old.finished_at
    assert events.last_failure is None
    assert events.stale


async def test_backfill_does_not_count_as_a_refresh(monkeypatch) -> None:
    backfill = _job(JobStatus.SUCCEEDED, 1, params={"mode": "window"})
    events = await _events(monkeypatch, [backfill])
    assert events.last_success is None  # only routine refreshes count
    assert events.stale
