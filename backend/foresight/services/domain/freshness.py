"""When each kind of data last refreshed for a hotel (decision 0039).

Read from `jobs` and `recommendation_snapshots`; nothing is stored. Only
routine refreshes count for events and weather: a backfill of last year doesn't
make upcoming rates fresh. Whether a date is too old is for the reader to judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from foresight.database.enums import JobKind, JobStatus
from foresight.repository import job as job_repo
from foresight.repository import recommendation as snapshot_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

# name: (job kind, params a run must have)
KINDS = {
    "events": (JobKind.EVENTS, {"mode": "recent"}),
    "weather": (JobKind.WEATHER, {"mode": "forecast"}),
    "hotel_data": (JobKind.PERFORMANCE, {}),
    "training": (JobKind.TRAIN, {}),
}


@dataclass(frozen=True, slots=True)
class Freshness:
    last_success: datetime | None  # None if it never succeeded
    last_failure: datetime | None  # set only if the latest attempt failed
    error: str | None  # why the latest attempt failed


@dataclass(frozen=True, slots=True)
class HotelFreshness:
    """One hotel: every kind of data in `KINDS`, plus its recommendations."""

    events: Freshness
    weather: Freshness
    hotel_data: Freshness
    training: Freshness
    # When a rate last changed. Recommendations aren't a job, so this never
    # has a failure: a request that fails stores nothing.
    recommendations: Freshness


async def get_freshness(session: AsyncSession, hotel_id: int) -> HotelFreshness:
    """Raises NotFoundError for an unknown hotel."""
    await get_hotel(session, hotel_id)
    result: dict[str, Freshness] = {}
    for name, (kind, params) in KINDS.items():
        latest = await job_repo.latest_finished_job(
            session, hotel_id=hotel_id, kind=kind, params=params
        )
        failed = latest is not None and latest.status != JobStatus.SUCCEEDED
        success = latest
        if failed:
            success = await job_repo.latest_finished_job(
                session,
                hotel_id=hotel_id,
                kind=kind,
                params=params,
                status=JobStatus.SUCCEEDED,
            )
        result[name] = Freshness(
            last_success=success.finished_at if success else None,
            last_failure=latest.finished_at if failed else None,
            error=latest.error if failed else None,
        )
    snapshot_at = await snapshot_repo.latest_snapshot_at(session, hotel_id)
    return HotelFreshness(
        **result,
        recommendations=Freshness(
            last_success=snapshot_at, last_failure=None, error=None
        ),
    )
