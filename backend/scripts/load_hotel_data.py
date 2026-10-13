import argparse
import asyncio
from decimal import Decimal

from foresight.database.session import async_session_factory, engine
from foresight.services.parsers.hotel_data_parser import HotelDataParser, persist


async def _load(parser):
    try:
        async with async_session_factory() as session:
            counts = await persist(parser, session)
            await session.commit()
    finally:
        await engine.dispose()
    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Parse a client hotel export and load it into Postgres."
    )
    parser.add_argument("--input", required=True, help="Path to the client CSV file.")
    parser.add_argument(
        "--hotel-name", required=True, help="Hotel this file belongs to."
    )
    parser.add_argument("--city", required=True, help="City the hotel is in.")
    parser.add_argument(
        "--base-rate",
        required=True,
        type=Decimal,
        help="Standard room rate the client prices against.",
    )
    parser.add_argument(
        "--lat", type=float, help="Hotel latitude, needed by the events ingester."
    )
    parser.add_argument(
        "--lon", type=float, help="Hotel longitude, needed by the events ingester."
    )
    args = parser.parse_args()

    hotel_parser = HotelDataParser(
        input_path=args.input,
        hotel_name=args.hotel_name,
        city=args.city,
        base_rate=args.base_rate,
        latitude=args.lat,
        longitude=args.lon,
    )
    hotel_parser.run()
    counts = asyncio.run(_load(hotel_parser))
    print(
        f"{args.hotel_name}: {sum(counts.values())} nights "
        f"({', '.join(f'{n} {outcome.value}' for outcome, n in counts.items())})"
    )


if __name__ == "__main__":
    main()
