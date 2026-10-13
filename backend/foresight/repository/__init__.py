"""Repository layer.

Encapsulates all database access. Repositories translate between ORM models
(`database.models`) and the rest of the application, so services and routes
never touch SQLAlchemy sessions directly.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession


class Outcome(StrEnum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


async def upsert_rows(
    session: AsyncSession,
    table: Table,
    *,
    constraint: str,
    key: Sequence[str],
    mutable: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> dict[Outcome, int]:
    """Upsert `rows` on `constraint`, touching a row only when a value changed.

    Does not commit; the caller owns the transaction. `key` must name the
    columns `constraint` covers: Postgres refuses to update a row twice in one
    statement, so repeats within a batch are collapsed to the last one first.
    """
    counts = dict.fromkeys(Outcome, 0)
    rows = list({tuple(r[c] for c in key): r for r in rows}.values())
    if not rows:
        return counts

    stmt = insert(table).values(rows)
    excluded = stmt.excluded
    set_: dict[str, Any] = {c: excluded[c] for c in mutable}
    # Only the external-signal tables record when a row was last fetched.
    if "captured_at" in table.c:
        set_["captured_at"] = func.clock_timestamp()
    stmt = stmt.on_conflict_do_update(
        constraint=constraint,
        set_=set_,
        # An unchanged row fails this, so it is never returned below.
        where=or_(*(table.c[c].is_distinct_from(excluded[c]) for c in mutable)),
        # xmax is 0 only on a freshly inserted tuple, never on a conflict update.
    ).returning(literal_column("(xmax = 0)").label("inserted"))

    for inserted in (await session.execute(stmt)).scalars():
        counts[Outcome.NEW if inserted else Outcome.UPDATED] += 1
    counts[Outcome.UNCHANGED] = (
        len(rows) - counts[Outcome.NEW] - counts[Outcome.UPDATED]
    )
    return counts
