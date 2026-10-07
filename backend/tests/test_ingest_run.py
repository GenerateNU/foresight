"""CLI argument parsing and the report shown at the end of a run."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from foresight.ingest.normalize import Source
from foresight.ingest.predicthq import Rejected
from foresight.ingest.repository import Outcome
from foresight.ingest.run import Market, RunReport, parse_since

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7d", datetime(2026, 9, 29, 12, 0, tzinfo=UTC)),
        ("12h", datetime(2026, 10, 6, 0, 0, tzinfo=UTC)),
        ("2w", datetime(2026, 9, 22, 12, 0, tzinfo=UTC)),
        ("2026-10-01", datetime(2026, 10, 1, tzinfo=UTC)),
    ],
)
def test_parse_since(value: str, expected: datetime) -> None:
    assert parse_since(value, now=NOW) == expected


def test_parse_since_rejects_garbage() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_since("last tuesday", now=NOW)


def test_report_lists_every_count_and_rejection() -> None:
    report = RunReport(
        source=Source.PREDICTHQ,
        market=Market(city="Dublin", latitude=53.3498, longitude=-6.2603),
        radius="10km",
        since=NOW,
        fetched=6,
        outcomes={Outcome.NEW: 1, Outcome.UPDATED: 2, Outcome.UNCHANGED: 2},
        rejected=[Rejected("phq-broken", "end precedes start")],
        events_by_status={"active": 4, "deleted": 1},
        observations_by_source={"predicthq": 5},
    )

    assert report.summary() == "fetched=6 new=1 updated=2 unchanged=2 rejected=1"
    rendered = report.render()
    for line in ("fetched       6", "updated       2", "rejected      1"):
        assert line in rendered
    assert "dublin now holds 5 events (4 active, 1 deleted)" in rendered
    assert "phq-broken" in rendered
