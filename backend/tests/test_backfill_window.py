from __future__ import annotations

from datetime import date

import pytest

from foresight.repository import hotel as hotel_repo
from foresight.services.backfill.window import hotel_window

HOTEL_RANGE = (date(2022, 3, 1), date(2025, 9, 30))


@pytest.fixture
def hotel_range(monkeypatch: pytest.MonkeyPatch):
    """Stand in for the DB: stay_date_range returns whatever the test sets."""
    answer = {"range": HOTEL_RANGE}

    async def fake_stay_date_range(session, hotel_id):
        return answer["range"]

    monkeypatch.setattr(hotel_repo, "stay_date_range", fake_stay_date_range)
    return answer


async def test_defaults_to_the_hotel_range(hotel_range) -> None:
    assert await hotel_window(None, 1, None, None) == HOTEL_RANGE


async def test_given_dates_win_over_the_hotel_range(hotel_range) -> None:
    start, end = date(2024, 1, 1), date(2024, 1, 31)

    assert await hotel_window(None, 1, start, None) == (start, HOTEL_RANGE[1])
    assert await hotel_window(None, 1, start, end) == (start, end)


async def test_both_dates_need_no_hotel(hotel_range) -> None:
    start, end = date(2024, 1, 1), date(2024, 1, 31)
    assert await hotel_window(None, None, start, end) == (start, end)


async def test_no_hotel_nights_needs_both_dates(hotel_range) -> None:
    hotel_range["range"] = None

    with pytest.raises(ValueError, match="no hotel nights loaded"):
        await hotel_window(None, 1, None, None)


async def test_missing_date_without_a_hotel_is_rejected(hotel_range) -> None:
    with pytest.raises(ValueError, match="no hotel nights loaded"):
        await hotel_window(None, None, date(2024, 1, 1), None)


async def test_start_after_end_is_rejected(hotel_range) -> None:
    with pytest.raises(ValueError, match="is after"):
        await hotel_window(None, None, date(2025, 1, 1), date(2024, 1, 1))
