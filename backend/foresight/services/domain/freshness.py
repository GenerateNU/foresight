"""When each kind of data last refreshed for a hotel, and whether it's stale.

Read from `jobs`; nothing is stored. Only routine refreshes count for events
and weather: a backfill of last year doesn't make upcoming rates fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from foresight.database.enums import JobKind, JobStatus
from foresight.repository import job as job_repo
from foresight.services.domain.hotel import get_hotel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# name: (job kind, params a run must have, how old it may get)
KINDS = {
    "events": (JobKind.EVENTS, {"mode": "recent"}, timedelta(days=1)),
    "weather": (JobKind.WEATHER, {"mode": "forecast"}, timedelta(days=1)),
    "hotel_data": (JobKind.PERFORMANCE, {}, timedelta(days=7)),
    "training": (JobKind.TRAIN, {}, timedelta(days=30)),
}


@dataclass(frozen=True, slots=True)
class Freshness:
    last_success: datetime | None  # None if it never succeeded
    last_failure: datetime | None  # set only if the latest attempt failed
    error: str | None  # why the latest attempt failed
    stale: bool


@dataclass(frozen=True, slots=True)
class HotelFreshness:
    """One hotel: every kind of data, keyed as in `KINDS`."""

    events: Freshness
    weather: Freshness
    hotel_data: Freshness
    training: Freshness
    recommendations: Freshness | None = None  # null until snapshots are stored


async def get_freshness(session: AsyncSession, hotel_id: int) -> HotelFreshness:
    """Raises NotFoundError for an unknown hotel."""
    await get_hotel(session, hotel_id)
    now = datetime.now(UTC)
    result: dict[str, Freshness] = {}
    for name, (kind, params, max_age) in KINDS.items():
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
            stale=success is None or now - success.finished_at > max_age,
        )
    return HotelFreshness(**result)
