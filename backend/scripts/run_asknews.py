"""Run the AskNews event ingest and print a cleaning report per run.

Two modes:

    uv run python scripts/run_asknews.py              # replay recorded batches
    uv run python scripts/run_asknews.py --live       # call the real API

Replay is the default so the pipeline can be demonstrated and regression-checked
without credentials or network. The extraction path is identical in both modes;
only where the articles come from differs.

Events are written through the shared upsert, so re-polling an overlapping
window visibly produces no duplicate rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from foresight.config import settings
from foresight.database.models.external import Event, EventObservation
from foresight.database.session import async_session_factory, engine
from foresight.ingest.asknews import (
    AskNewsClient,
    CityTarget,
    IngestReport,
    collect_events,
    extract_batch,
)
from foresight.ingest.repository import Outcome, upsert_event

if TYPE_CHECKING:
    from collections.abc import Sequence

    from foresight.ingest.normalize import NormalizedEvent

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "asknews"

# The cities we sell rooms in. Everything else AskNews returns is noise.
CITIES = (
    CityTarget("Dublin", "Europe/Dublin", "IE", aliases=("Baile Atha Cliath",)),
    CityTarget("Lisbon", "Europe/Lisbon", "PT", aliases=("Lisboa",)),
    CityTarget("Edinburgh", "Europe/London", "GB"),
)


async def persist(events: Sequence[NormalizedEvent]) -> Counter[Outcome]:
    """Write a run through the shared upsert, one transaction per run."""
    counts: Counter[Outcome] = Counter()
    async with async_session_factory() as session:
        for event in events:
            counts[await upsert_event(session, event)] += 1
        await session.commit()
    return counts


async def stored_events() -> tuple[list[Event], int]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(Event).order_by(Event.start_local_date, Event.title)
        )
        observations = await session.scalar(
            select(func.count()).select_from(EventObservation)
        )
        return list(rows), observations or 0


def load_fixture(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


async def run_live(
    today: date, hours_back: int, per_query: int
) -> tuple[list[NormalizedEvent], IngestReport]:
    """Exactly the call a scheduled worker makes. The CLI adds nothing to it."""
    import httpx

    if not (settings.asknews_client_id and settings.asknews_client_secret):
        raise SystemExit(
            "ASKNEWS_CLIENT_ID and ASKNEWS_CLIENT_SECRET must be set for --live"
        )
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = AskNewsClient(
            settings.asknews_client_id, settings.asknews_client_secret, http=http
        )
        return await collect_events(
            client,
            CITIES,
            today=today,
            articles_per_query=per_query,
            hours_back=hours_back,
        )


def describe(event: NormalizedEvent | Event) -> str:
    """Same fields on the extracted object and the stored row."""
    return (
        f"    {event.start_local_date} .. {event.end_local_date}  "
        f"{event.city_slug:<10} {event.date_precision:<8} "
        f"conf {event.confidence:.2f}  {event.title}"
    )


def print_run(
    label: str,
    source: str,
    report: IngestReport,
    events: Sequence[NormalizedEvent],
    counts: Counter[Outcome] | None,
) -> None:
    print(f"\n{'=' * 68}\n{label}  --  {source}\n{'=' * 68}")
    print(report.render())
    if counts is None:
        print("extracted (nothing written)")
        for event in events:
            print(describe(event))
        return
    print("written to the events table")
    for outcome in Outcome:
        print(f"    {outcome.value:<22} {counts[outcome]}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="call AskNews instead of replaying"
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what was extracted instead of writing to the database",
    )
    parser.add_argument("--hours-back", type=int, default=24)
    parser.add_argument("--articles-per-query", type=int, default=50)
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=datetime.now().date(),
        help="reference date for 'is this event still ahead of us'",
    )
    args = parser.parse_args()

    totals = IngestReport()

    for index in range(1, args.runs + 1):
        if args.live:
            events, report = await run_live(
                args.today, args.hours_back, args.articles_per_query
            )
            source = f"live, last {args.hours_back}h"
        else:
            path = FIXTURE_DIR / f"run_{index}.json"
            if not path.exists():
                print(f"no fixture for run {index} at {path}")
                break
            events, report = extract_batch(load_fixture(path), CITIES, today=args.today)
            report.queries_run = 1
            source = f"replay {path.name}"

        counts = None if args.dry_run else await persist(events)
        print_run(f"RUN {index}", source, report, events, counts)

        totals.articles_seen += report.articles_seen
        totals.events_kept += report.events_kept
        totals.rejected.update(report.rejected)

    print(f"\n{'=' * 68}\nACROSS ALL RUNS\n{'=' * 68}")
    print(f"articles processed {totals.articles_seen}")
    print(f"articles rejected  {totals.articles_rejected}")
    for reason, count in totals.rejected.most_common():
        print(f"    {reason:<22} {count}")
    if args.dry_run:
        return 0

    rows, observations = await stored_events()
    print(f"rows in events     {len(rows)}")
    print(f"rows in observations {observations}")
    for event in rows:
        print(describe(event))
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
