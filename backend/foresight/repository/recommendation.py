from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.recommendation import RecommendationSnapshot


async def create_recommendation_snapshot(
    session: AsyncSession,
    *,
    hotel_id: int,
    room_type_id: int,
    stay_date: date,
    model_id: int,
    rate: Decimal,
    factors: dict[str, Any],
    inputs: dict[str, Any],
) -> RecommendationSnapshot:
    """Adds a snapshot of one night's rate as shown now; never updates a row.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        room_type_id (int): The room type.
        stay_date (date): The night.
        model_id (int): The version that priced it.
        rate (Decimal): The rate, before VAT.
        factors (dict[str, Any]): The explanation, as JSON.
        inputs (dict[str, Any]): What the model read, as JSON.

    Returns:
        RecommendationSnapshot: The new snapshot.
    """
    snapshot = RecommendationSnapshot(
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        stay_date=stay_date,
        model_id=model_id,
        rate=rate,
        factors=factors,
        inputs=inputs,
    )
    session.add(snapshot)
    await session.flush()
    await session.refresh(snapshot)
    return snapshot


async def get_snapshot(
    session: AsyncSession, snapshot_id: int
) -> RecommendationSnapshot | None:
    """Gets a snapshot.

    Args:
        session (AsyncSession): The database session.
        snapshot_id (int): The snapshot.

    Returns:
        RecommendationSnapshot | None: The snapshot, or None if it doesn't
            exist.
    """
    return await session.get(RecommendationSnapshot, snapshot_id)


async def latest_snapshots(
    session: AsyncSession, room_type_id: int, *, start: date, end: date
) -> dict[date, RecommendationSnapshot]:
    """Gets the newest snapshot of each night in a window that has one.

    The id breaks ties between snapshots saved in one transaction, which share
    `created_at`.

    Args:
        session (AsyncSession): The database session.
        room_type_id (int): The room type.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        dict[date, RecommendationSnapshot]: Each night's newest snapshot.
    """
    stmt = (
        select(RecommendationSnapshot)
        .distinct(RecommendationSnapshot.stay_date)
        .where(
            RecommendationSnapshot.room_type_id == room_type_id,
            RecommendationSnapshot.stay_date.between(start, end),
        )
        .order_by(
            RecommendationSnapshot.stay_date,
            RecommendationSnapshot.created_at.desc(),
            RecommendationSnapshot.id.desc(),
        )
    )
    return {s.stay_date: s for s in await session.scalars(stmt)}


async def snapshotted_nights(
    session: AsyncSession, room_type_id: int, *, start: date, end: date
) -> Sequence[Mapping[str, Any]]:
    """Lists each night in a window that has a snapshot, from its newest one.

    Args:
        session (AsyncSession): The database session.
        room_type_id (int): The room type.
        start (date): First night, inclusive.
        end (date): Last night, inclusive.

    Returns:
        Sequence[Mapping[str, Any]]: One row per night, oldest first, with
            stay_date, shown_at (when the snapshot was made) and rate.
    """
    stmt = (
        select(
            RecommendationSnapshot.stay_date,
            RecommendationSnapshot.created_at.label("shown_at"),
            RecommendationSnapshot.rate,
        )
        .distinct(RecommendationSnapshot.stay_date)
        .where(
            RecommendationSnapshot.room_type_id == room_type_id,
            RecommendationSnapshot.stay_date.between(start, end),
        )
        .order_by(
            RecommendationSnapshot.stay_date,
            RecommendationSnapshot.created_at.desc(),
            RecommendationSnapshot.id.desc(),
        )
    )
    return (await session.execute(stmt)).mappings().all()


async def latest_snapshot_at(session: AsyncSession, hotel_id: int) -> datetime | None:
    """Finds when the hotel's newest snapshot was saved.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        datetime | None: When, or None if it has none.
    """
    return await session.scalar(
        select(func.max(RecommendationSnapshot.created_at)).where(
            RecommendationSnapshot.hotel_id == hotel_id
        )
    )
