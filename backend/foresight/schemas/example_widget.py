"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

Pydantic shapes for the `Widget` reference slice.

Layer rules shown here:
- `*Request` schemas describe a request body: only the fields a client may set.
- `*Response` schemas describe what an endpoint returns, built from an ORM
  object. Each lists its fields explicitly; Request and Response never inherit
  from each other.
- See `agents/schemas.md` for the full standard.
"""

from foresight.schemas.base import RequestSchema, ResponseSchema


class WidgetRequest(RequestSchema):
    name: str
    description: str | None = None
    quantity: int = 0


class WidgetResponse(ResponseSchema):
    id: int
    name: str
    description: str | None
    quantity: int
