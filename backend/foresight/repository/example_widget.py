"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

Data access for the `Widget` reference slice. This is the canonical repository
pattern for Foresight.

Layer rules shown here:
- This is the ONLY layer that imports ORM models and uses the session.
- Functions are `async` and receive an `AsyncSession` — they never open their
  own session or manage the engine.
- Construct/return ORM models here; callers pass plain values and map to schemas
  themselves, so services stay persistence-agnostic.
- No business logic lives here — just queries and persistence.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.example_widget import Widget


async def create_widget(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    quantity: int,
) -> Widget:
    widget = Widget(name=name, description=description, quantity=quantity)
    session.add(widget)
    await session.commit()
    await session.refresh(widget)
    return widget


async def get_widget(session: AsyncSession, widget_id: int) -> Widget | None:
    return await session.get(Widget, widget_id)


async def list_widgets(session: AsyncSession) -> Sequence[Widget]:
    result = await session.execute(select(Widget).order_by(Widget.id))
    return result.scalars().all()
