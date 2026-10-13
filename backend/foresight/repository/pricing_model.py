"""Data access for `pricing_models`: trained model versions per hotel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update

from foresight.database.models.pricing_model import PricingModel

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession


async def create_pricing_model(
    session: AsyncSession,
    *,
    hotel_id: int,
    algorithm: str,
    artifact: bytes,
    features: list[str],
    metrics: dict[str, Any],
    lib_versions: dict[str, str],
    data_start: date,
    data_end: date,
) -> PricingModel:
    """Save a new, inactive model as the hotel's next version.

    Call `activate_pricing_model` afterwards to start serving it.
    """
    model = PricingModel(
        hotel_id=hotel_id,
        version=await _next_version(session, hotel_id),
        algorithm=algorithm,
        artifact=artifact,
        features=features,
        metrics=metrics,
        lib_versions=lib_versions,
        data_start=data_start,
        data_end=data_end,
        is_active=False,
    )
    session.add(model)
    await session.flush()
    await session.refresh(model)
    return model


async def get_pricing_model(
    session: AsyncSession, model_id: int
) -> PricingModel | None:
    return await session.get(PricingModel, model_id)


async def get_active_pricing_model(
    session: AsyncSession, hotel_id: int
) -> PricingModel | None:
    """The model currently serving the hotel, if any."""
    return await session.scalar(
        select(PricingModel).where(
            PricingModel.hotel_id == hotel_id, PricingModel.is_active
        )
    )


async def activate_pricing_model(
    session: AsyncSession, model_id: int
) -> PricingModel | None:
    """Make this model the hotel's active one, deactivating any other.

    Both writes land in the caller's transaction, so once it commits the hotel
    is never left with zero or two active models. Returns None if the model
    doesn't exist.
    """
    model = await session.get(PricingModel, model_id)
    if model is None:
        return None

    # Deactivate first: the partial unique index allows one active row.
    await session.execute(
        update(PricingModel)
        .where(
            PricingModel.hotel_id == model.hotel_id,
            PricingModel.is_active,
            PricingModel.id != model.id,
        )
        .values(is_active=False)
    )
    await session.flush()
    model.is_active = True
    await session.flush()
    await session.refresh(model)
    return model


async def _next_version(session: AsyncSession, hotel_id: int) -> int:
    current = await session.scalar(
        select(func.coalesce(func.max(PricingModel.version), 0)).where(
            PricingModel.hotel_id == hotel_id
        )
    )
    return (current or 0) + 1
