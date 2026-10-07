"""Fetch external events and upsert them into the canonical tables.

    python -m foresight.ingest.run --source predicthq --since 7d --hotel-id 1 --report
    python -m foresight.ingest.run --source predicthq --since 90d \\
        --lat 53.3498 --lon -6.2603 --city Dublin --report
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from foresight.config import settings
from foresight.database.models.external import Event, EventObservation
from foresight.database.models.hotel import Hotel
from foresight.database.session import async_session_factory, engine
from foresight.ingest import predicthq
from foresight.ingest.normalize import Source, slugify_city
from foresight.ingest.repository import Outcome, upsert_event

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.ingest.predicthq import Rejected

log = logging.getLogger("foresight.ingest")

_SPAN = re.compile(r"^(\d+)([hdw])$")
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


@dataclass(slots=True)
class Market:
    city: str
    latitude: float
    longitude: float


@dataclass(slots=True)
class RunReport:
    source: Source
    market: Market
    radius: str
    since: datetime
    fetched: int = 0
    outcomes: dict[Outcome, int] = field(default_factory=dict)
    rejected: list[Rejected] = field(default_factory=list)
    events_by_status: dict[str, int] = field(default_factory=dict)
    observations_by_source: dict[str, int] = field(default_factory=dict)

    def count(self, outcome: Outcome) -> int:
        return self.outcomes.get(outcome, 0)

    def summary(self) -> str:
        return (
            f"fetched={self.fetched} new={self.count(Outcome.NEW)} "
            f"updated={self.count(Outcome.UPDATED)} "
            f"unchanged={self.count(Outcome.UNCHANGED)} "
            f"rejected={len(self.rejected)}"
        )

    def render(self) -> str:
        m = self.market
        rule = "  " + "-" * 15
        lines = [
            f"{self.source.value} ingest | {m.city} | "
            f"{self.radius} around {m.latitude:.4f}, {m.longitude:.4f}",
            f"revised upstream since {self.since:%Y-%m-%d %H:%M} UTC",
            "",
            f"  {'fetched':<11}{self.fetched:>4}",
            rule,
            *(f"  {outcome.value:<11}{self.count(outcome):>4}" for outcome in Outcome),
            f"  {'rejected':<11}{len(self.rejected):>4}",
            "",
            f"  {slugify_city(m.city)} now holds "
            f"{sum(self.events_by_status.values())} events "
            f"({_breakdown(self.events_by_status)})",
            f"  backed by {sum(self.observations_by_source.values())} observations "
            f"({_breakdown(self.observations_by_source)})",
        ]
        if self.rejected:
            lines += ["", "  rejected records:"]
            lines += [f"    {r.source_ref:<22} {r.reason}" for r in self.rejected]
        return "\n".join(lines)


def _breakdown(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "none"


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    """`7d`, `12h`, `2w`, or an ISO date/datetime (UTC if no offset given)."""
    if match := _SPAN.match(value.strip().lower()):
        amount, unit = int(match[1]), match[2]
        return (now or datetime.now(UTC)) - timedelta(**{_UNITS[unit]: amount})
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a span like 7d, 12h, 2w or an ISO date, got {value!r}"
        ) from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m foresight.ingest.run", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--source", choices=[Source.PREDICTHQ.value], required=True)
    parser.add_argument(
        "--since",
        type=parse_since,
        default="7d",
        help="only records revised upstream since then (default: 7d)",
    )
    parser.add_argument("--hotel-id", type=int, help="use this hotel's stored lat/lon")
    parser.add_argument("--lat", type=float, help="market latitude (no --hotel-id)")
    parser.add_argument("--lon", type=float, help="market longitude (no --hotel-id)")
    parser.add_argument("--city", help="market city (no --hotel-id)")
    parser.add_argument("--radius", default="10km", help="e.g. 10km, 5mi")
    parser.add_argument("--report", action="store_true", help="print a full run report")
    return parser


async def _resolve_market(session: AsyncSession, args: argparse.Namespace) -> Market:
    if args.hotel_id is None:
        return Market(city=args.city, latitude=args.lat, longitude=args.lon)

    hotel = await session.get(Hotel, args.hotel_id)
    if hotel is None:
        raise SystemExit(f"error: no hotel with id {args.hotel_id}")
    if hotel.latitude is None or hotel.longitude is None:
        raise SystemExit(f"error: hotel {hotel.id} ({hotel.name}) has no lat/lon")
    return Market(city=hotel.city, latitude=hotel.latitude, longitude=hotel.longitude)


async def _market_totals(
    session: AsyncSession, city: str
) -> tuple[dict[str, int], dict[str, int]]:
    slug = slugify_city(city)
    by_status = await session.execute(
        select(Event.status, func.count())
        .where(Event.city_slug == slug)
        .group_by(Event.status)
    )
    by_source = await session.execute(
        select(EventObservation.source, func.count())
        .join(Event, EventObservation.event_id == Event.id)
        .where(Event.city_slug == slug)
        .group_by(EventObservation.source)
    )
    return (
        {status.value: n for status, n in by_status.all()},
        {source.value: n for source, n in by_source.all()},
    )


async def run(args: argparse.Namespace) -> RunReport:
    async with async_session_factory() as session:
        market = await _resolve_market(session, args)
        report = RunReport(
            source=Source(args.source),
            market=market,
            radius=args.radius,
            since=args.since,
        )

        result = await predicthq.fetch_events(
            token=settings.predicthq_token,
            latitude=market.latitude,
            longitude=market.longitude,
            city=market.city,
            updated_since=args.since,
            radius=args.radius,
        )
        report.fetched = result.fetched
        report.rejected = result.rejected

        for event in result.events:
            outcome = await upsert_event(session, event)
            report.outcomes[outcome] = report.outcomes.get(outcome, 0) + 1
        await session.commit()

        report.events_by_status, report.observations_by_source = await _market_totals(
            session, market.city
        )
    return report


async def _main(args: argparse.Namespace) -> None:
    try:
        report = await run(args)
    finally:
        await engine.dispose()
    print(report.render() if args.report else report.summary())


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.hotel_id is None and None in (args.lat, args.lon, args.city):
        parser.error("give --hotel-id, or all of --lat, --lon and --city")
    if args.source == Source.PREDICTHQ and not settings.predicthq_token:
        parser.error("PREDICTHQ_TOKEN is not set; add it to .env")

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    # DEBUG=true turns on SQL echo, which would bury the report.
    engine.echo = False
    asyncio.run(_main(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
