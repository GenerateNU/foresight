r"""Download historical airport arrivals from OpenSky in 2-day chunks.

Each chunk is saved as its own CSV in ``data/flights/opensky/`` and chunks that already
exist are skipped, so re-running the same command resumes where it stopped. The script
stops when OpenSky's daily credit limit is reached.

OpenSky allows at most 2 days per arrivals request. A request covering up to 2 UTC days
costs 30 credits and a standard account gets 4,000 credits a day, so a day's credits
cover about 133 chunks (about 266 days of flights). Dates are UTC days so that every
request stays within 2 UTC days. Only flights up to yesterday (UTC) are available.

Example:
    Run from ``backend/``::

        uv run python scripts/fetch_opensky.py --start 2022-01-01 --end 2025-12-31
"""

import argparse
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import httpx
import pandas as pd

from foresight.config import settings

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "flights" / "opensky"
ARRIVAL_URL = "https://opensky-network.org/api/flights/arrival"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"


def get_token() -> str:
    """Get an OpenSky access token, which expires after 30 minutes.

    Returns:
        str: The bearer token.

    Raises:
        httpx.HTTPStatusError: If authentication fails.
    """
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.opensky_client_id,
            "client_secret": settings.opensky_client_secret,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> None:
    """Download arrivals for a date range, one CSV per 2-day chunk."""
    parser = argparse.ArgumentParser(
        description="Download OpenSky airport arrivals in 2-day chunks."
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, required=True, help="YYYY-MM-DD (UTC)"
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        help="YYYY-MM-DD (UTC), defaults to yesterday",
    )
    parser.add_argument(
        "--airport", default="EIDW", help="ICAO code, defaults to Dublin (EIDW)"
    )
    args = parser.parse_args()

    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    end = min(args.end or yesterday, yesterday)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    token = get_token()

    for offset in range(0, (end - args.start).days + 1, 2):
        first = args.start + timedelta(days=offset)
        last = min(first + timedelta(days=1), end)
        path = OUTPUT_DIR / f"{args.airport}_{first}_{last}.csv"
        if path.exists():
            continue

        # Midnight UTC to the last second of ``last``: never more than 2 UTC days.
        begin = datetime.combine(first, time.min, UTC)
        until = datetime.combine(last + timedelta(days=1), time.min, UTC)
        params = {
            "airport": args.airport,
            "begin": int(begin.timestamp()),
            "end": int(until.timestamp()) - 1,
        }
        for _ in range(2):
            response = httpx.get(
                ARRIVAL_URL,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
            if response.status_code != 401:
                break
            token = get_token()  # the token expired, so get a new one and retry

        if response.status_code == 429:
            wait = response.headers.get("X-Rate-Limit-Retry-After-Seconds")
            print(f"Credit limit reached, retry in {wait}s. Re-run to resume.")
            return
        if response.status_code == 404:  # no flights in this chunk
            rows = []
        else:
            response.raise_for_status()
            rows = response.json()
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"{first} to {last}: {len(rows)} flights")


if __name__ == "__main__":
    main()
