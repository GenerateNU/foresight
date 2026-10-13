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
    """Run an ordered SELECT and return one page of it plus the unpaged row count."""
    count_stmt: Select[Any] = select(func.count()).select_from(
        stmt.order_by(None).subquery()
    )
    total = await session.scalar(count_stmt)
    result = await session.scalars(stmt.limit(limit).offset(offset))
    return result.all(), total or 0
