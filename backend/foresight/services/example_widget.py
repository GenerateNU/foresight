"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

Business logic for the `Widget` reference slice.

Layer rules shown here:
- Services hold domain logic and orchestration; they call the repository for
  persistence and never touch the ORM/session directly.
- Services take plain arguments (never a schema) and return domain data (ORM
  models or dataclasses) — never `*Response` schemas or status codes.
- When an operation can't go ahead, raise an error from `services/errors.py`
  (`NotFoundError`, `ConflictError`, ...); `routes/errors.py` maps it to HTTP.
  `get_x(id)` raises NotFoundError rather than returning None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foresight.repository import example_widget as widget_repo
from foresight.services.errors import NotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.example_widget import Widget


async def create_widget(
    session: AsyncSession, *, name: str, description: str | None, quantity: int
) -> Widget:
    return await widget_repo.create_widget(
        session, name=name, description=description, quantity=quantity
    )


async def get_widget(session: AsyncSession, widget_id: int) -> Widget:
    widget = await widget_repo.get_widget(session, widget_id)
    if widget is None:
        raise NotFoundError("Widget", widget_id)
    return widget


async def list_widgets(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[Sequence[Widget], int]:
    return await widget_repo.list_widgets(session, limit=limit, offset=offset)
