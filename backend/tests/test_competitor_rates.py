from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.database.models.signals.competitor_rate import CompetitorRate
from foresight.repository.signals.competitor_rate import upsert_competitor_rates
from foresight.repository.upsert import Outcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CITY = "Testville"


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "hotel_name": "The Rival",
        "city": CITY,
        "stay_date": date(2026, 6, 1),
        "rate": Decimal("189.00"),
        "is_sold_out": False,
        "source": "test-scraper",
    } | overrides


async def _rows(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(CompetitorRate)
        .where(CompetitorRate.city == CITY)
    )


async def test_first_write_is_new(session: AsyncSession) -> None:
    counts = await upsert_competitor_rates(session, [_row()])
    assert counts[Outcome.NEW] == 1
    assert await _rows(session) == 1


async def test_identical_rerun_adds_no_rows(session: AsyncSession) -> None:
    await upsert_competitor_rates(session, [_row()])
    counts = await upsert_competitor_rates(session, [_row()])
    assert counts == {Outcome.NEW: 0, Outcome.UPDATED: 0, Outcome.UNCHANGED: 1}
    assert await _rows(session) == 1


async def test_revised_rate_updates_in_place(session: AsyncSession) -> None:
    await upsert_competitor_rates(session, [_row()])
    counts = await upsert_competitor_rates(session, [_row(rate=Decimal("215.50"))])
    assert counts[Outcome.UPDATED] == 1
    assert await _rows(session) == 1
    assert await session.scalar(
        select(CompetitorRate.rate).where(CompetitorRate.city == CITY)
    ) == Decimal("215.50")


async def test_selling_out_is_an_update(session: AsyncSession) -> None:
    # rate goes to NULL: IS DISTINCT FROM must still see it as a change.
    await upsert_competitor_rates(session, [_row()])
    counts = await upsert_competitor_rates(session, [_row(rate=None, is_sold_out=True)])
    assert counts[Outcome.UPDATED] == 1
    assert await _rows(session) == 1


async def test_sold_out_rerun_is_unchanged(session: AsyncSession) -> None:
    # NULL == NULL must not count as a change, or every re-run would "update".
    sold_out = _row(rate=None, is_sold_out=True)
    await upsert_competitor_rates(session, [sold_out])
    counts = await upsert_competitor_rates(session, [sold_out])
    assert counts[Outcome.UNCHANGED] == 1


async def test_each_competitor_and_night_is_its_own_row(
    session: AsyncSession,
) -> None:
    await upsert_competitor_rates(
        session,
        [
            _row(),
            _row(hotel_name="The Other Place"),
            _row(stay_date=date(2026, 6, 2)),
        ],
    )
    assert await _rows(session) == 3


async def test_second_source_is_its_own_row(session: AsyncSession) -> None:
    await upsert_competitor_rates(session, [_row(), _row(source="other-scraper")])
    assert await _rows(session) == 2


async def test_duplicate_key_in_one_batch_keeps_the_last(
    session: AsyncSession,
) -> None:
    counts = await upsert_competitor_rates(
        session, [_row(), _row(rate=Decimal("199.00"))]
    )
    assert counts[Outcome.NEW] == 1
    assert await session.scalar(
        select(CompetitorRate.rate).where(CompetitorRate.city == CITY)
    ) == Decimal("199.00")


async def test_empty_batch_writes_nothing(session: AsyncSession) -> None:
    assert await upsert_competitor_rates(session, []) == dict.fromkeys(Outcome, 0)
    assert await _rows(session) == 0
