import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from datetime import date

from foresight.config import settings
from foresight.database.session import async_session_factory, engine
from foresight.ingest.run import market_totals, migrate, resolve_market
from foresight.services.backfill.events import BackfillReport, backfill
from foresight.services.backfill.window import hotel_window


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/backfill/backfill_events.py",
        description="Backfill PredictHQ events for a date range.",
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the hotel's"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the hotel's"
    )
    parser.add_argument(
        "--hotel-id", type=int, help="use this hotel's city and lat/lon"
    )
    parser.add_argument("--lat", type=float, help="market latitude (no --hotel-id)")
    parser.add_argument("--lon", type=float, help="market longitude (no --hotel-id)")
    parser.add_argument("--city", help="market city (no --hotel-id)")
    parser.add_argument("--radius", default="10km", help="e.g. 10km, 5mi")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and normalize, without writing to the database",
    )
    return parser


async def _run(args: argparse.Namespace) -> BackfillReport:
    try:
        async with async_session_factory() as session:
            market = await resolve_market(session, args)
            try:
                start, end = await hotel_window(
                    session, args.hotel_id, args.start, args.end
                )
            except ValueError as exc:
                raise SystemExit(f"error: {exc}") from exc
            report = None
            async for progress in backfill(
                None if args.dry_run else session,
                market,
                start,
                end,
                token=settings.predicthq_token,
                radius=args.radius,
            ):
                report = progress
                if not args.dry_run:
                    await session.commit()  # keep each finished month
            if report is None:
                raise SystemExit("error: empty date range")
            if not args.dry_run:
                by_status, by_source = await market_totals(session, market.city)
                print(
                    f"{market.city}: events by status {by_status}, "
                    f"observations by source {by_source}"
                )
    finally:
        await engine.dispose()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.hotel_id is None and None in (args.lat, args.lon, args.city):
        parser.error("give --hotel-id, or all of --lat, --lon and --city")
    if not settings.predicthq_token:
        parser.error("PREDICTHQ_TOKEN is not set; add it to .env")

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    if not args.dry_run:
        migrate()
    engine.echo = False  # DEBUG=true would bury the report in SQL
    report = asyncio.run(_run(args))

    print(report.summary())
    for r in report.rejected:
        print(f"  rejected {r.source_ref:<22} {r.reason}")
    if report.overflow_chunks:
        print(f"  overflow (plan truncated): {report.overflow_chunks}")
    if report.stopped:
        print(f"stopped: {report.stopped}", file=sys.stderr)
        print(
            f"saved everything before it; resume with --start {report.resume_from}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
