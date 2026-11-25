from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from foresight.database.models.model import PricingModel
from foresight.repository.pagination import fetch_page


async def create_model(
    session: AsyncSession,
    *,
    hotel_id: int,
    algorithm: str,
    description: str | None,
    artifact: bytes,
    features: list[str],
    metrics: dict[str, Any],
    lib_versions: dict[str, str],
    data_start: date,
    data_end: date,
    room_type_id: int,
    base_model_id: int | None = None,
) -> PricingModel:
    """Saves a model as the hotel's next version, inactive.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        algorithm (str): `ebm` or `ebm-tuned`.
        description (str | None): What this version tries.
        artifact (bytes): The serialized model.
        features (list[str]): Its input columns, in order.
        metrics (dict[str, Any]): What it trained on and what it cost.
        lib_versions (dict[str, str]): Library versions, to load the artifact.
        data_start (date): First night trained on.
        data_end (date): Last night trained on.
        room_type_id (int): The room type it prices.
        base_model_id (int | None): For a tune-up, the version it corrects.

    Returns:
        PricingModel: The saved version.
    """
    version_row = PricingModel(
        hotel_id=hotel_id,
        version=await _next_version(session, hotel_id),
        algorithm=algorithm,
        description=description,
        artifact=artifact,
        features=features,
        metrics=metrics,
        lib_versions=lib_versions,
        data_start=data_start,
        data_end=data_end,
        room_type_id=room_type_id,
        base_model_id=base_model_id,
        is_active=False,
    )
    session.add(version_row)
    await session.flush()
    await session.refresh(version_row)
    return version_row


async def get_model(session: AsyncSession, model_id: int) -> PricingModel | None:
    """Gets a version without its artifact.

    Args:
        session (AsyncSession): The database session.
        model_id (int): The version.

    Returns:
        PricingModel | None: The version, or None if it doesn't exist.
    """
    return await session.scalar(
        select(PricingModel)
        .options(defer(PricingModel.artifact))
        .where(PricingModel.id == model_id)
    )


async def list_models(
    session: AsyncSession, hotel_id: int, *, limit: int, offset: int
) -> tuple[Sequence[PricingModel], int]:
    """Lists one page of the hotel's versions, newest first, without artifacts.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        limit (int): Most versions to return.
        offset (int): Versions to skip.

    Returns:
        tuple[Sequence[PricingModel], int]: The page, and how many there are.
    """
    stmt = (
        select(PricingModel)
        .options(defer(PricingModel.artifact))
        .where(PricingModel.hotel_id == hotel_id)
        .order_by(PricingModel.version.desc())
    )
    return await fetch_page(session, stmt, limit=limit, offset=offset)


async def get_active_model(session: AsyncSession, hotel_id: int) -> PricingModel | None:
    """Gets the version serving the hotel, without its artifact.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        PricingModel | None: The active version, or None if there isn't one.
    """
    return await session.scalar(
        select(PricingModel)
        .options(defer(PricingModel.artifact))
        .where(PricingModel.hotel_id == hotel_id, PricingModel.is_active)
    )


async def get_artifact(session: AsyncSession, model_id: int) -> bytes | None:
    """Gets a version's serialized model.

    Args:
        session (AsyncSession): The database session.
        model_id (int): The version.

    Returns:
        bytes | None: The artifact, or None if the version doesn't exist.
    """
    return await session.scalar(
        select(PricingModel.artifact).where(PricingModel.id == model_id)
    )


async def activate_model(session: AsyncSession, model_id: int) -> PricingModel | None:
    """Makes a version its hotel's active one, deactivating any other.

    Both writes land in the caller's transaction, so once it commits the hotel
    never has zero or two active versions. The other is deactivated first,
    since a partial unique index allows one active row per hotel.

    Args:
        session (AsyncSession): The database session.
        model_id (int): The version.

    Returns:
        PricingModel | None: The version, or None if it doesn't exist.
    """
    version_row = await get_model(session, model_id)
    if version_row is None:
        return None
    await session.execute(
        update(PricingModel)
        .where(
            PricingModel.hotel_id == version_row.hotel_id,
            PricingModel.is_active,
            PricingModel.id != version_row.id,
        )
        .values(is_active=False)
    )
    await session.flush()
    version_row.is_active = True
    await session.flush()
    await session.refresh(version_row)
    return version_row


async def _next_version(session: AsyncSession, hotel_id: int) -> int:
    """Works out the hotel's next version number.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.

    Returns:
        int: One more than its highest version, or 1.
    """
    current = await session.scalar(
        select(func.coalesce(func.max(PricingModel.version), 0)).where(
            PricingModel.hotel_id == hotel_id
        )
    )
    return (current or 0) + 1
