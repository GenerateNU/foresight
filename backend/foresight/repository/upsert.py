from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import Table, func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.base import Base

_MAX_PARAMS = 32_767


class Outcome(StrEnum):
    """What an upsert did to one row."""

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
    keep_if_null: Sequence[str] = (),
) -> dict[Outcome, int]:
    """Upserts rows on a constraint, touching a row only when a value changed.

    Postgres refuses to update a row twice in one statement, so repeats within
    a batch are collapsed to the last one first. Rows go in batches that stay
    under Postgres's limit of 32,767 parameters per statement. Does not commit.

    Args:
        session (AsyncSession): The database session.
        model (type[Base]): The table's model.
        constraint (str): The unique constraint to upsert on.
        key (Sequence[str]): The columns that constraint covers.
        mutable (Sequence[str]): The columns an update may change.
        rows (Iterable[Mapping[str, Any]]): The rows to save.
        keep_if_null (Sequence[str]): Columns where a null leaves the stored
            value alone.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
    table = cast("Table", model.__table__)
    counts = dict.fromkeys(Outcome, 0)
    rows = list({tuple(r[c] for c in key): r for r in rows}.values())
    if not rows:
        return counts
    batch = max(1, _MAX_PARAMS // len(rows[0]))
    for i in range(0, len(rows), batch):
        outcomes = await _upsert_batch(
            session, table, constraint, mutable, keep_if_null, rows[i : i + batch]
        )
        for outcome, n in outcomes.items():
            counts[outcome] += n
    return counts


async def _upsert_batch(
    session: AsyncSession,
    table: Table,
    constraint: str,
    mutable: Sequence[str],
    keep_if_null: Sequence[str],
    rows: list[Mapping[str, Any]],
) -> dict[Outcome, int]:
    """Upserts one batch in one statement.

    An unchanged row fails the update's condition, so it's never returned.
    `xmax` is 0 only on a freshly inserted row, which tells new from updated.

    Args:
        session (AsyncSession): The database session.
        table (Table): The table.
        constraint (str): The unique constraint to upsert on.
        mutable (Sequence[str]): The columns an update may change.
        keep_if_null (Sequence[str]): Columns where a null keeps the stored
            value.
        rows (list[Mapping[str, Any]]): The batch.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
    counts = dict.fromkeys(Outcome, 0)
    stmt = insert(table).values(rows)
    excluded = stmt.excluded
    set_: dict[str, Any] = {
        c: func.coalesce(excluded[c], table.c[c]) if c in keep_if_null else excluded[c]
        for c in mutable
    }
    changed = or_(*(table.c[c].is_distinct_from(set_[c]) for c in mutable))
    if "captured_at" in table.c:
        set_["captured_at"] = func.clock_timestamp()
    stmt = stmt.on_conflict_do_update(
        constraint=constraint, set_=set_, where=changed
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    for inserted in (await session.execute(stmt)).scalars():
        counts[Outcome.NEW if inserted else Outcome.UPDATED] += 1
    counts[Outcome.UNCHANGED] = (
        len(rows) - counts[Outcome.NEW] - counts[Outcome.UPDATED]
    )
    return counts
