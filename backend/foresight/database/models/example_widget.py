"""REFERENCE EXAMPLE — copy this pattern; do not use in production.

The `Widget` model is a throwaway entity used to demonstrate a full vertical
slice (database -> repository -> service -> route). Delete it once real models
have replaced the need for a reference.

Layer rules shown here:
- Models define *what* the data looks like; they contain no query logic.
- Use async SQLAlchemy 2.0 typed mappings (`Mapped[...]` + `mapped_column`).
- Every model must be importable from `database/models/__init__.py` so Alembic
  autogenerate can see it.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class Widget(Base):
    __tablename__ = "example_widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(default=0)
