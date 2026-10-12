from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.pricing_model import PricingModel


async def create(
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
    """Saves a new, inactive model as the hotel's next version.

    Call `activate` afterwards to start serving it.
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
    await session.commit()
    await session.refresh(model)
    return model


async def get(session: AsyncSession, model_id: int) -> PricingModel | None:
    return await session.get(PricingModel, model_id)


async def get_active(session: AsyncSession, hotel_id: int) -> PricingModel | None:
    """Returns the model currently serving the hotel, if any."""
    result = await session.execute(
        select(PricingModel).where(
            PricingModel.hotel_id == hotel_id, PricingModel.is_active
        )
    )
    return result.scalar_one_or_none()


async def activate(session: AsyncSession, model_id: int) -> PricingModel | None:
    """Makes this model the hotel's active one, deactivating any other.

    Both changes commit together, so the hotel is never left with zero or two
    active models. Returns None if the model doesn't exist.
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
    await session.commit()
    await session.refresh(model)
    return model


async def _next_version(session: AsyncSession, hotel_id: int) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(PricingModel.version), 0)).where(
            PricingModel.hotel_id == hotel_id
        )
    )
    return result.scalar_one() + 1
