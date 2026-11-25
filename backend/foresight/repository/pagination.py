from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_page[T](
    session: AsyncSession,
    stmt: Select[tuple[T]],
    *,
    limit: int,
    offset: int,
) -> tuple[Sequence[T], int]:
    """Runs an ordered query and returns one page of it.

    Args:
        session (AsyncSession): The database session.
        stmt (Select[tuple[T]]): The ordered query.
        limit (int): Most rows to return.
        offset (int): Rows to skip.

    Returns:
        tuple[Sequence[T], int]: The page, and how many rows the query has.
    """
    count_stmt: Select[Any] = select(func.count()).select_from(
        stmt.order_by(None).subquery()
    )
    total = await session.scalar(count_stmt)
    result = await session.scalars(stmt.limit(limit).offset(offset))
    return result.all(), total or 0
