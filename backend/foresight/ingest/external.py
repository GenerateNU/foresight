from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from typing import TYPE_CHECKING

from foresight.database.session import async_session_factory, engine
from foresight.ingest.flights import daily_arrivals
from foresight.ingest.weather import fetch_actuals, fetch_forecast
from foresight.repository.flights import upsert_flight_arrivals
from foresight.repository.weather import upsert_weather
from foresight.services.flight_data_service import fetch_aerodatabox, fetch_opensky

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.repository import Outcome

# shortcut: every flight provider is hardcoded to Dublin, so there is nothing
# for an --airport flag to vary yet; add one when a second airport appears.
AIRPORT = "DUB"
_FLIGHT_PROVIDERS = {"opensky": fetch_opensky, "aerodatabox": fetch_aerodatabox}


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a date like 2026-10-05, got {value!r}"
        ) from None


async def _weather(
    session: AsyncSession, args: argparse.Namespace
) -> dict[Outcome, int]:
    if args.start is None:
        rows = fetch_forecast(args.city, args.lat, args.lon, "auto")
    else:
        # The archive refuses a future end date outright instead of returning
        # empty days, so a range running past today has to be clamped here.
        rows = fetch_actuals(
            args.city,
            args.lat,
            args.lon,
            "auto",
            start=args.start,
            end=min(args.end, date.today()),
        )
    return await upsert_weather(session, rows)


async def _flights(
    session: AsyncSession, args: argparse.Namespace
) -> dict[Outcome, int]:
    frame = _FLIGHT_PROVIDERS[args.source](args.start, args.end)
    rows = daily_arrivals(frame, airport=AIRPORT, source=args.source)
    return await upsert_flight_arrivals(session, rows)


async def run(args: argparse.Namespace) -> dict[Outcome, int]:
    handler = _weather if args.source == "weather" else _flights
    async with async_session_factory() as session:
        counts = await handler(session, args)
        await session.commit()
    return counts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m foresight.ingest.external",
        description="Fetch one external source and upsert it into its table.",
    )
    parser.add_argument(
        "--source", choices=["weather", *_FLIGHT_PROVIDERS], required=True
    )
    parser.add_argument("--start", type=_parse_date, help="first day, inclusive")
    parser.add_argument("--end", type=_parse_date, help="last day, inclusive")
    parser.add_argument("--city", help="weather only: the name stored on each row")
    parser.add_argument("--lat", type=float, help="weather only")
    parser.add_argument("--lon", type=float, help="weather only")
    return parser


async def _main(args: argparse.Namespace) -> dict[Outcome, int]:
    try:
        return await run(args)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.source == "weather":
        if None in (args.city, args.lat, args.lon):
            parser.error("--source weather needs --city, --lat and --lon")
        if (args.start is None) != (args.end is None):
            parser.error("give both --start and --end, or neither for a forecast")
    elif None in (args.start, args.end):
        parser.error(f"--source {args.source} needs --start and --end")
    if None not in (args.start, args.end) and args.start > args.end:
        parser.error("--start is after --end")

    engine.echo = False
    counts = asyncio.run(_main(args))
    total = sum(counts.values())
    print(
        f"{args.source}: {total} rows "
        f"({', '.join(f'{n} {outcome.value}' for outcome, n in counts.items())})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
