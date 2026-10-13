import argparse
import asyncio
import logging
import sys
from datetime import date

from foresight.config import settings
from foresight.database.session import async_session_factory, engine
from foresight.ingest.run import migrate
from foresight.services.backfill.flights import (
    FlightBackfillStoppedError,
    backfill_flights,
)
from foresight.services.backfill.window import hotel_window

log = logging.getLogger("foresight.backfill")


async def _run(args: argparse.Namespace) -> date | None:
    """Backfill day by day, committing each. Returns the day a limit stopped on."""
    try:
        async with async_session_factory() as session:
            try:
                start, end = await hotel_window(
                    session, args.hotel_id, args.start, args.end
                )
            except ValueError as exc:
                raise SystemExit(f"error: {exc}") from exc
            try:
                async for day, count in backfill_flights(
                    session, start, end, args.airport
                ):
                    await session.commit()  # keep each finished day
                    log.info("%s: %d arrivals saved", day, count)
            except FlightBackfillStoppedError as exc:
                log.error("%s", exc)
                return exc.day
    finally:
        await engine.dispose()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Save the number of flights arriving each day, from AeroDataBox."
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the hotel's"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the hotel's"
    )
    parser.add_argument("--hotel-id", type=int, help="default the dates to this hotel")
    parser.add_argument("--airport", default="DUB", help="IATA code (default: DUB)")
    args = parser.parse_args()
    args.airport = args.airport.upper()
    if not settings.xrapidapi_key:
        parser.error("XRAPIDAPI_KEY is not set; add it to .env")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate()
    engine.echo = False
    stopped_on = asyncio.run(_run(args))
    if stopped_on:
        print(f"resume with --start {stopped_on}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
