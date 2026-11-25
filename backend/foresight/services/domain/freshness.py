from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import JobKind, JobStatus
from foresight.repository import job as job_repo
from foresight.repository import recommendation as recommendation_repo
from foresight.services.domain.hotel import get_hotel

KINDS = {
    "events": (JobKind.EVENTS, {"mode": "recent"}),
    "hotel_data": (JobKind.RESERVATIONS, {}),
    "training": (JobKind.TRAIN, {}),
}


@dataclass(frozen=True, slots=True)
class Freshness:
    """When one kind of data last refreshed.

    Attributes:
        last_success (datetime | None): The latest success; None if it never
            succeeded.
        last_failure (datetime | None): Set only if the latest attempt failed.
        error (str | None): Why the latest attempt failed.
    """

    last_success: datetime | None
    last_failure: datetime | None
    error: str | None


@dataclass(frozen=True, slots=True)
class HotelFreshness:
    """When each kind of a hotel's data last refreshed.

    Attributes:
        events (Freshness): The routine events refresh.
        hotel_data (Freshness): The bookings training reads.
        training (Freshness): Training.
        recommendations (Freshness): When a rate last changed. Never has a
            failure: a request that fails stores nothing.
    """

    events: Freshness
    hotel_data: Freshness
    training: Freshness
    recommendations: Freshness


async def get_freshness(session: AsyncSession, hotel_id: int) -> HotelFreshness:
    """Says when each kind of data last refreshed for a hotel.

    Read from `jobs` and `recommendation_snapshots`; nothing is stored. Each
    of `KINDS` is a job kind plus the params a run must have: only routine
    refreshes count for events, since a backfill of last year doesn't make
    upcoming rates fresh. Whether a date is too old is for the reader to
    judge.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        HotelFreshness: Each kind's latest success and failure.

    Raises:
        NotFoundError: The hotel doesn't exist.
    """
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
    snapshot_at = await recommendation_repo.latest_snapshot_at(session, hotel_id)
    return HotelFreshness(
        **result,
        recommendations=Freshness(
            last_success=snapshot_at, last_failure=None, error=None
        ),
    )
