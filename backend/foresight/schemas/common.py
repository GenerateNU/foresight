"""Shapes shared by every list endpoint."""

from pydantic import BaseModel


class Page[T](BaseModel):
    """One page of a list endpoint: the rows plus where they sit in the full set."""

    items: list[T]
    total: int  # rows matching the filters, ignoring limit/offset
    limit: int
    offset: int
