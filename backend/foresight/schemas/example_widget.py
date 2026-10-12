"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

Pydantic shapes for the `Widget` reference slice.

Layer rules shown here:
- `*Create` schemas describe the request body (no `id`, no server fields).
- `*Read` schemas describe the response and set `from_attributes=True` so they
  can be built directly from an ORM model instance.
"""

from pydantic import BaseModel, ConfigDict


class WidgetCreate(BaseModel):
    name: str
    description: str | None = None
    quantity: int = 0


class WidgetRead(WidgetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
