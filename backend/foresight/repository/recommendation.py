"""Data access for `recommendation_snapshots`: every rate recommended, per night."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from foresight.database.models.recommendation import RecommendationSnapshot

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession


async def create_recommendation_snapshot(
    session: AsyncSession,
    *,
    hotel_id: int,
    room_type_id: int,
    stay_date: date,
    model_id: int,
    model_version: str,
    rate: Decimal,
    interval_low: Decimal,
    interval_high: Decimal,
    uncertainty: Decimal,
    factors: dict[str, Any],
) -> RecommendationSnapshot:
    """Save a new recommendation snapshot for a hotel.

    This captures the recommended rates and associated metadata at a specific
    point in time.
    """
    snapshot = RecommendationSnapshot(
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        stay_date=stay_date,
        model_id=model_id,
        model_version=model_version,
        rate=rate,
        interval_low=interval_low,
        interval_high=interval_high,
        uncertainty=uncertainty,
        factors=factors,
    )
    session.add(snapshot)
    await session.flush()
    await session.refresh(snapshot)
    return snapshot


async def get_latest_snapshot(
    session: AsyncSession, room_type_id: int, *, stay_date: date
) -> RecommendationSnapshot | None:
    """The newest snapshot for this room type and night, or None if there isn't one."""
    return await session.scalar(_night_history(room_type_id, stay_date).limit(1))


async def get_previous_snapshot(
    session: AsyncSession, room_type_id: int, *, stay_date: date
) -> RecommendationSnapshot | None:
    """The snapshot before the newest one for this room type and night, or None."""
    return await session.scalar(
        _night_history(room_type_id, stay_date).offset(1).limit(1)
    )


def _night_history(
    room_type_id: int, stay_date: date
) -> Select[tuple[RecommendationSnapshot]]:
    """One night's snapshots, newest first. The id breaks ties: rows saved in
    one transaction share the same `created_at`."""
    return (
        select(RecommendationSnapshot)
        .where(
            RecommendationSnapshot.room_type_id == room_type_id,
            RecommendationSnapshot.stay_date == stay_date,
        )
        .order_by(
            RecommendationSnapshot.created_at.desc(), RecommendationSnapshot.id.desc()
        )
    )
