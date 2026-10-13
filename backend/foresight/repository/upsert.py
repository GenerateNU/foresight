"""Bulk upsert shared by every table with a natural key."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.base import Base

# Postgres allows at most 32,767 bind parameters in one statement.
_MAX_PARAMS = 32_767


class Outcome(StrEnum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


async def upsert_rows(
    session: AsyncSession,
    model: type[Base],
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
    table = cast("Table", model.__table__)
    counts = dict.fromkeys(Outcome, 0)
    rows = list({tuple(r[c] for c in key): r for r in rows}.values())
    if not rows:
        return counts

    # One statement per batch, sized to stay under the parameter limit.
    batch = max(1, _MAX_PARAMS // len(rows[0]))
    for i in range(0, len(rows), batch):
        for outcome, n in (
            await _upsert_batch(
                session, table, constraint, mutable, rows[i : i + batch]
            )
        ).items():
            counts[outcome] += n
    return counts


async def _upsert_batch(
    session: AsyncSession,
    table: Table,
    constraint: str,
    mutable: Sequence[str],
    rows: list[Mapping[str, Any]],
) -> dict[Outcome, int]:
    counts = dict.fromkeys(Outcome, 0)
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
