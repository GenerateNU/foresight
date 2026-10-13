import argparse
import asyncio
from datetime import date

from foresight.database.session import async_session_factory, engine
from foresight.services.backfill.weather_coverage import weather_coverage
from foresight.services.backfill.window import hotel_window


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report recorded-weather coverage for a city over a date range."
    )
    parser.add_argument("--city", required=True, help="market city, e.g. Dublin")
    parser.add_argument("--hotel-id", type=int, help="default the dates to this hotel")
    parser.add_argument(
        "--start", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the hotel's"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the hotel's"
    )
    return parser


async def main() -> int:
    parser = _parser()
    args = parser.parse_args()

    engine.echo = False
    try:
        async with async_session_factory() as session:
            try:
                start, end = await hotel_window(
                    session, args.hotel_id, args.start, args.end
                )
            except ValueError as exc:
                parser.error(str(exc))
            report = await weather_coverage(
                session, city=args.city, start=start, end=end
            )
    finally:
        await engine.dispose()

    print(f"weather | {report.city} | {report.start} → {report.end}")
    print(f"  rows:            {report.rows} of {report.days} days")
    print(f"  earliest usable: {report.earliest or 'none'}")
    for label, spans in (("missing:", report.missing), ("no values:", report.empty)):
        gaps = ", ".join(str(a) if a == b else f"{a} → {b}" for a, b in spans)
        print(f"  {label:<16} {gaps or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
