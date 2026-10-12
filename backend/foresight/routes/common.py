"""Pieces shared by the route modules: session, pagination, 404s."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.session import get_session
from foresight.schemas.common import Page

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass
class Pagination:
    """`?limit=&offset=` query params shared by every list endpoint."""

    limit: Annotated[int, Query(ge=1, le=200)] = 50
    offset: Annotated[int, Query(ge=0)] = 0


PageDep = Annotated[Pagination, Depends()]


def paginate[T: BaseModel](
    schema: type[T], rows: Sequence[Any], total: int, page: Pagination
) -> Page[T]:
    """Map ORM rows to `schema` and wrap them in the shared page envelope."""
    return Page(
        items=[schema.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def not_found(entity: str, entity_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{entity} {entity_id} not found",
    )
