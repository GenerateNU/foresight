"""Run the AskNews event ingest and print a cleaning report per run.

Two modes:

    uv run python scripts/run_asknews.py              # replay recorded batches
    uv run python scripts/run_asknews.py --live       # call the real API

Replay is the default so the pipeline can be demonstrated and regression-checked
without credentials or network. The extraction path is identical in both modes;
only where the articles come from differs.

Across runs the script tracks what is genuinely new, so re-polling an
overlapping window visibly produces no duplicate events.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from foresight.config import settings
from foresight.ingest.asknews import (
    AskNewsClient,
    CityTarget,
    IngestReport,
    collect_events,
    extract_batch,
)

if TYPE_CHECKING:
    from foresight.ingest.normalize import NormalizedEvent

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "asknews"

# The cities we sell rooms in. Everything else AskNews returns is noise.
CITIES = (
    CityTarget("Dublin", "Europe/Dublin", "IE", aliases=("Baile Atha Cliath",)),
    CityTarget("Lisbon", "Europe/Lisbon", "PT", aliases=("Lisboa",)),
    CityTarget("Edinburgh", "Europe/London", "GB"),
)


@dataclass
class EventStore:
    """Stands in for the events table so the demo needs no database.

    Keyed the same way the real upsert is -- on `dedupe_key` -- so the new /
    repeat / revised counts here are the counts the repository would produce.
    """

    by_key: dict[str, NormalizedEvent] = field(default_factory=dict)
    key_by_ref: dict[str, str] = field(default_factory=dict)

    def apply(self, events: list[NormalizedEvent]) -> dict[str, list[str]]:
        outcome: dict[str, list[str]] = {"new": [], "repeat": [], "revised": []}
        for event in events:
            previous_key = self.key_by_ref.get(event.source_ref)
            if previous_key and previous_key != event.dedupe_key:
                # Same article, different date: dedupe_key includes the start
                # date, so a correction lands as a new row rather than an edit.
                outcome["revised"].append(
                    f"{event.title} -> {event.start_local_date} "
                    f"(was {self.by_key[previous_key].start_local_date})"
                )
                self.by_key.pop(previous_key, None)
            elif event.dedupe_key in self.by_key:
                outcome["repeat"].append(event.title)
            else:
                outcome["new"].append(f"{event.title} ({event.start_local_date})")
            self.by_key[event.dedupe_key] = event
            self.key_by_ref[event.source_ref] = event.dedupe_key
        return outcome


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


def print_run(
    label: str,
    source: str,
    report: IngestReport,
    outcome: dict[str, list[str]],
) -> None:
    print(f"\n{'=' * 68}\n{label}  --  {source}\n{'=' * 68}")
    print(report.render())
    print("against what we already had")
    for kind in ("new", "repeat", "revised"):
        print(f"    {kind:<22} {len(outcome[kind])}")
        for line in outcome[kind]:
            print(f"        {line}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="call AskNews instead of replaying"
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--hours-back", type=int, default=24)
    parser.add_argument("--articles-per-query", type=int, default=50)
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=datetime.now().date(),
        help="reference date for 'is this event still ahead of us'",
    )
    args = parser.parse_args()

    store = EventStore()
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

        print_run(f"RUN {index}", source, report, store.apply(events))

        totals.articles_seen += report.articles_seen
        totals.events_kept += report.events_kept
        totals.rejected.update(report.rejected)

    print(f"\n{'=' * 68}\nACROSS ALL RUNS\n{'=' * 68}")
    print(f"articles processed {totals.articles_seen}")
    print(f"articles rejected  {totals.articles_rejected}")
    for reason, count in totals.rejected.most_common():
        print(f"    {reason:<22} {count}")
    print(f"distinct events    {len(store.by_key)}")
    for event in sorted(store.by_key.values(), key=lambda e: e.start_local_date):
        print(
            f"    {event.start_local_date} .. {event.end_local_date}  "
            f"{event.city_slug:<10} {event.date_precision:<8} "
            f"conf {event.confidence:.2f}  {event.title}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
