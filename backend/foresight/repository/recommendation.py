"""Data access for `recommendation_snapshots`: every rate recommended, per night."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.database.models.recommendation import RecommendationSnapshot

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

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
    interval_level: float,
    uncertainty: Decimal,
    factors: dict[str, Any],
    inputs: dict[str, Any],
    inputs_hash: str,
) -> RecommendationSnapshot:
    """Add a snapshot: one night's rate, as priced now. Never updates a row."""
    snapshot = RecommendationSnapshot(
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        stay_date=stay_date,
        model_id=model_id,
        model_version=model_version,
        rate=rate,
        interval_low=interval_low,
        interval_high=interval_high,
        interval_level=interval_level,
        uncertainty=uncertainty,
        factors=factors,
        inputs=inputs,
        inputs_hash=inputs_hash,
    )
    session.add(snapshot)
    await session.flush()
    await session.refresh(snapshot)
    return snapshot


async def latest_snapshots(
    session: AsyncSession, room_type_id: int, *, start: date, end: date
) -> dict[date, RecommendationSnapshot]:
    """The newest snapshot for each night in [start, end] that has one."""
    stmt = (
        select(RecommendationSnapshot)
        .distinct(RecommendationSnapshot.stay_date)
        .where(
            RecommendationSnapshot.room_type_id == room_type_id,
            RecommendationSnapshot.stay_date.between(start, end),
        )
        # The id breaks ties: rows saved in one transaction share `created_at`.
        .order_by(
            RecommendationSnapshot.stay_date,
            RecommendationSnapshot.created_at.desc(),
            RecommendationSnapshot.id.desc(),
        )
    )
    return {s.stay_date: s for s in await session.scalars(stmt)}


async def latest_snapshot_at(session: AsyncSession, hotel_id: int) -> datetime | None:
    """When the hotel's newest snapshot was saved, or None if it has none."""
    return await session.scalar(
        select(func.max(RecommendationSnapshot.created_at)).where(
            RecommendationSnapshot.hotel_id == hotel_id
        )
    )
