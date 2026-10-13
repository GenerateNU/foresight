from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from foresight.repository import weather as weather_repo
from foresight.services.backfill.weather_coverage import weather_coverage

if TYPE_CHECKING:
    import pytest


def _saved(monkeypatch: pytest.MonkeyPatch, days: dict[date, bool]) -> None:
    async def fake_recorded_days(session, *, city, start, end):
        return days

    monkeypatch.setattr(weather_repo, "recorded_days", fake_recorded_days)


async def test_counts_rows_and_groups_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    _saved(
        monkeypatch,
        {
            date(2024, 3, 1): False,
            date(2024, 3, 2): True,
            date(2024, 3, 5): True,
            date(2024, 3, 6): False,
        },
    )

    report = await weather_coverage(
        None, city="Dublin", start=date(2024, 3, 1), end=date(2024, 3, 7)
    )

    assert (report.days, report.rows) == (7, 4)
    assert report.earliest == date(2024, 3, 2)
    assert report.missing == [
        (date(2024, 3, 3), date(2024, 3, 4)),
        (date(2024, 3, 7), date(2024, 3, 7)),
    ]
    assert report.empty == [
        (date(2024, 3, 1), date(2024, 3, 1)),
        (date(2024, 3, 6), date(2024, 3, 6)),
    ]


async def test_nothing_saved_is_one_big_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    _saved(monkeypatch, {})

    report = await weather_coverage(
        None, city="Dublin", start=date(2024, 3, 1), end=date(2024, 3, 31)
    )

    assert report.rows == 0
    assert report.earliest is None
    assert report.missing == [(date(2024, 3, 1), date(2024, 3, 31))]
