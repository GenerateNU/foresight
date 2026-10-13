"""Daily flight arrivals for a hotel's airport, fetched and saved day by day."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from foresight.repository.flight import upsert_flight_arrivals
from foresight.services.errors import DomainError
from foresight.services.ingest import aerodatabox, opensky
from foresight.services.ingest.aerodatabox import RateLimitedError
from foresight.services.ingest.opensky import CreditsExhaustedError, OpenSkyClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import date

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel


class MissingAirportError(DomainError):
    """The hotel lacks the airport code or timezone a source needs."""


class FlightBackfillStoppedError(Exception):
    """The source's quota ran out; `day` is the first day not saved."""

    def __init__(self, day: date, reason: str) -> None:
        super().__init__(f"stopped on {day}: {reason}")
        self.day = day


async def _save(session: AsyncSession, airport: str, day: date, n: int, src: str):
    await upsert_flight_arrivals(
        session,
        [
            {
                "airport": airport,
                "arrival_date": day,
                "flight_count": n,
                "avg_fare_eur": None,  # no source carries fares
                "source": src,
            }
        ],
    )


async def backfill_aerodatabox(
    session: AsyncSession,
    hotel: Hotel,
    start: date,
    end: date,
    *,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[tuple[date, int]]:
    """Scheduled arrivals per day at the hotel's IATA airport.

    Yields (day, count) after each day is written so the caller can commit
    as it goes. Does not commit itself.

    Raises:
        MissingAirportError: If the hotel has no IATA code.
        FlightBackfillStoppedError: On the monthly quota; every day yielded
            before it is complete.
    """
    if not hotel.airport_iata:
        raise MissingAirportError(f"hotel {hotel.id} has no airport_iata")
    async with aerodatabox.client(api_key, transport=transport) as http:
        day = start
        while day <= end:
            try:
                n = await aerodatabox.count_arrivals(
                    http, day, airport_iata=hotel.airport_iata
                )
            except RateLimitedError as exc:
                raise FlightBackfillStoppedError(day, str(exc)) from exc
            await _save(session, hotel.airport_iata, day, n, aerodatabox.SOURCE)
            yield day, n
            day += timedelta(days=1)


async def backfill_opensky(
    session: AsyncSession,
    hotel: Hotel,
    start: date,
    end: date,
    *,
    client_id: str,
    client_secret: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[tuple[date, int]]:
    """Tracked arrivals per local day at the hotel's ICAO airport.

    Yields (day, count) after each day is written. Stored under the hotel's
    ICAO code, since that's what OpenSky reports against.

    Raises:
        MissingAirportError: If the hotel has no ICAO code or timezone.
        FlightBackfillStoppedError: When the daily credits run out.
    """
    if not hotel.airport_icao or not hotel.timezone:
        raise MissingAirportError(
            f"hotel {hotel.id} needs airport_icao and timezone for OpenSky"
        )
    last_saved: date | None = None
    async with OpenSkyClient(client_id, client_secret, transport=transport) as sky:
        try:
            async for day, n in sky.daily_arrivals(
                start, end, airport_icao=hotel.airport_icao, timezone=hotel.timezone
            ):
                await _save(session, hotel.airport_icao, day, n, opensky.SOURCE)
                last_saved = day
                yield day, n
        except CreditsExhaustedError as exc:
            resume = start if last_saved is None else last_saved + timedelta(days=1)
            raise FlightBackfillStoppedError(resume, str(exc)) from exc
