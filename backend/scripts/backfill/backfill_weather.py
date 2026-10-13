import argparse
import asyncio
from datetime import date

from foresight.database.session import async_session_factory, engine
from foresight.ingest.run import resolve_market
from foresight.services.backfill.weather import backfill_weather
from foresight.services.backfill.window import hotel_window


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill recorded weather for a city over a date range."
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
    parser.add_argument("--city", help="market city (no --hotel-id)")
    parser.add_argument("--lat", type=float, help="market latitude (no --hotel-id)")
    parser.add_argument("--lon", type=float, help="market longitude (no --hotel-id)")
    return parser


async def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.hotel_id is None and None in (args.city, args.lat, args.lon):
        parser.error("give --hotel-id, or all of --city, --lat and --lon")

    engine.echo = False
    try:
        async with async_session_factory() as session:
            market = await resolve_market(session, args)
            try:
                start, end = await hotel_window(
                    session, args.hotel_id, args.start, args.end
                )
            except ValueError as exc:
                parser.error(str(exc))
            counts = await backfill_weather(
                session,
                city=market.city,
                latitude=market.latitude,
                longitude=market.longitude,
                start=start,
                end=end,
            )
            await session.commit()
    finally:
        await engine.dispose()

    summary = ", ".join(f"{n} {outcome.value}" for outcome, n in counts.items())
    print(f"weather | {market.city} | {start} → {end} | {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
