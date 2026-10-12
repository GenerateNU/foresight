"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

HTTP layer for the `Widget` reference slice.

Layer rules shown here:
- Routers are thin: validate input via schemas, call a service, shape the
  response. No business logic and no ORM/session access here.
- Inject the session with `Depends(get_session)` and pass it down.
- Translate domain results into HTTP (e.g. a missing record -> 404).
- Register the router in `foresight/main.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.session import get_session
from foresight.schemas.example_widget import WidgetCreate, WidgetRead
from foresight.services import example_widget as widget_service

router = APIRouter(prefix="/example/widgets", tags=["example"])

# Reusable session dependency. Using `Annotated` (instead of a `Depends(...)`
# default value) keeps the FastAPI DI pattern lint-clean.
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=WidgetRead, status_code=status.HTTP_201_CREATED)
async def create_widget(
    data: WidgetCreate,
    session: SessionDep,
) -> WidgetRead:
    widget = await widget_service.create_widget(session, data)
    return WidgetRead.model_validate(widget)


@router.get("", response_model=list[WidgetRead])
async def list_widgets(
    session: SessionDep,
) -> list[WidgetRead]:
    widgets = await widget_service.list_widgets(session)
    return [WidgetRead.model_validate(w) for w in widgets]


@router.get("/{widget_id}", response_model=WidgetRead)
async def get_widget(
    widget_id: int,
    session: SessionDep,
) -> WidgetRead:
    widget = await widget_service.get_widget(session, widget_id)
    if widget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Widget {widget_id} not found",
        )
    return WidgetRead.model_validate(widget)
