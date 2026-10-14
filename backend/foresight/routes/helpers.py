"""Shared by every router: schema bases, the session, and pagination.

Each route module defines the `*Request`/`*Response` schemas it uses, on the
two bases here. Services never see them: handlers pass plain arguments down
and map what comes back with `*Response.model_validate`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


class RequestSchema(BaseModel):
    """Base for request bodies. Unknown fields are rejected with a 422."""

    model_config = ConfigDict(extra="forbid")


class ResponseSchema(BaseModel):
    """Base for response bodies. Can be built from an ORM object or dataclass."""

    model_config = ConfigDict(from_attributes=True)


class PageResponse[T](ResponseSchema):
    """One page of a list endpoint: the rows plus where they sit in the full set."""

    items: list[T]
    total: int  # rows matching the filters, ignoring limit/offset
    limit: int
    offset: int


@dataclass
class Pagination:
    """`?limit=&offset=` query params for lists that can grow without bound."""

    limit: Annotated[int, Query(ge=1, le=200)] = 50
    offset: Annotated[int, Query(ge=0)] = 0


PageDep = Annotated[Pagination, Depends()]


def paginate[T: ResponseSchema](
    schema: type[T], rows: Sequence[Any], total: int, page: Pagination
) -> PageResponse[T]:
    """Map ORM rows to `schema` and wrap them in the shared page envelope."""
    return PageResponse(
        items=[schema.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
