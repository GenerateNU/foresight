"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

Business logic for the `Widget` reference slice.

Layer rules shown here:
- Services hold domain logic and orchestration; they call the repository for
  persistence and never touch the ORM/session directly.
- Services take plain inputs or schemas and return domain data (ORM models or
  simple values) — never HTTP responses or status codes.
- Map request schemas to repository calls here so the repository stays
  schema-agnostic.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.models.example_widget import Widget
from foresight.repository import example_widget as widget_repo
from foresight.schemas.example_widget import WidgetCreate


async def create_widget(session: AsyncSession, data: WidgetCreate) -> Widget:
    return await widget_repo.create_widget(
        session,
        name=data.name,
        description=data.description,
        quantity=data.quantity,
    )


async def get_widget(session: AsyncSession, widget_id: int) -> Widget | None:
    return await widget_repo.get_widget(session, widget_id)


async def list_widgets(session: AsyncSession) -> Sequence[Widget]:
    return await widget_repo.list_widgets(session)
