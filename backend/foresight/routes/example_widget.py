"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

HTTP layer for the `Widget` reference slice.

Layer rules shown here:
- One router per domain module, registered in `foresight/main.py`.
- The `*Request`/`*Response` schemas live in the route module that uses them,
  on the bases in `routes/helpers.py`. See decision 0015.
- Handlers are thin: take a `*Request`, pass plain arguments to one service
  function, map the result with `*Response.model_validate`. No business
  logic, no ORM/session; services never see a schema.
- Use the shared dependencies from `routes/helpers.py`: `SessionDep` (one
  transaction per request, committed by `get_session`) and `PageDep` +
  `paginate` for lists that can grow without bound.
- Services raise when something is missing (`NotFoundError`, `ConflictError`,
  ...); `routes/errors.py` maps those to HTTP, so handlers don't check or
  catch.
- Every handler declares `response_model=` and has a docstring: both appear in
  `/docs`.
"""

from fastapi import APIRouter, status
from pydantic import Field

from foresight.routes.helpers import (
    PageDep,
    PageResponse,
    RequestSchema,
    ResponseSchema,
    SessionDep,
    paginate,
)
from foresight.services import example_widget as widget_service

router = APIRouter(prefix="/example/widgets", tags=["example"])


# Request and Response never inherit from each other. Constraints and
# descriptions go in `Field(...)` so they are enforced and shown in /docs.
class WidgetRequest(RequestSchema):
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=500)
    quantity: int = Field(default=0, ge=0, description="Units in stock")


class WidgetResponse(ResponseSchema):
    id: int
    name: str
    description: str | None
    quantity: int


@router.post("", response_model=WidgetResponse, status_code=status.HTTP_201_CREATED)
async def create_widget(data: WidgetRequest, session: SessionDep) -> WidgetResponse:
    """Create a widget."""
    widget = await widget_service.create_widget(session, **data.model_dump())
    return WidgetResponse.model_validate(widget)


@router.get("", response_model=PageResponse[WidgetResponse])
async def list_widgets(
    session: SessionDep, page: PageDep
) -> PageResponse[WidgetResponse]:
    """Every widget, oldest first."""
    widgets, total = await widget_service.list_widgets(
        session, limit=page.limit, offset=page.offset
    )
    return paginate(WidgetResponse, widgets, total, page)


@router.get("/{widget_id}", response_model=WidgetResponse)
async def get_widget(widget_id: int, session: SessionDep) -> WidgetResponse:
    """One widget."""
    widget = await widget_service.get_widget(session, widget_id)
    return WidgetResponse.model_validate(widget)
