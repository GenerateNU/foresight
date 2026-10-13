from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest

from foresight.ingest import external
from foresight.repository import Outcome

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_TODAY = date.today()


def _args(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(
        **{
            "source": "weather",
            "start": None,
            "end": None,
            "city": "Dublin",
            "lat": 53.3,
            "lon": -6.2,
        }
        | overrides
    )


@pytest.mark.parametrize(
    ("end", "requested"),
    [
        (date(2025, 6, 7), date(2025, 6, 7)),
        # The archive rejects a future end date outright instead of returning
        # empty days, so an over-long range has to be trimmed before the call.
        (_TODAY + timedelta(days=30), _TODAY),
    ],
)
async def test_the_archive_is_never_asked_past_today(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    end: date,
    requested: date,
) -> None:
    seen: dict[str, date] = {}

    def _fake(*_: Any, start: date, end: date) -> list[dict[str, Any]]:
        seen.update(start=start, end=end)
        return []

    monkeypatch.setattr(external, "fetch_actuals", _fake)
    await external._weather(session, _args(start=date(2025, 6, 1), end=end))
    assert seen == {"start": date(2025, 6, 1), "end": requested}


async def test_no_dates_fetches_the_forecast(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(external, "fetch_forecast", lambda *_: [])
    monkeypatch.setattr(
        external, "fetch_actuals", lambda *_, **__: pytest.fail("called the archive")
    )
    assert await external._weather(session, _args()) == dict.fromkeys(Outcome, 0)


async def test_flight_provider_rows_reach_the_table(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {
            "arrival_time": pd.to_datetime(
                ["2026-06-01T08:00Z", "2026-06-01T12:00Z"], utc=True
            ).tz_convert("Europe/Dublin")
        }
    )
    monkeypatch.setitem(external._FLIGHT_PROVIDERS, "opensky", lambda *_: frame)
    counts = await external._flights(
        session, _args(source="opensky", start=date(2026, 6, 1), end=date(2026, 6, 1))
    )
    assert counts[Outcome.NEW] == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--source", "weather"],
        ["--source", "weather", "--city", "Dublin", "--lat", "53.3"],
        # fmt: off
        [
            "--source",
            "weather",
            "--city",
            "D",
            "--lat",
            "1",
            "--lon",
            "2",
            "--start",
            "2026-06-01",
        ],
        # fmt: on
        ["--source", "opensky"],
        ["--source", "opensky", "--start", "2026-06-07", "--end", "2026-06-01"],
    ],
)
def test_incomplete_arguments_are_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        external.main(argv)
    assert exit_info.value.code == 2
