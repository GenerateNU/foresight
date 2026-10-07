r"""Fetch flight data from the CSO, OpenSky and AeroDataBox and save it as CSV.

Dates and times are in Dublin local time (Europe/Dublin).

Example:
    Run from ``backend/``::

        uv run python foresight/services/flight_data_service.py \
            --start 2026-06-01 --end 2026-06-07
        uv run python foresight/services/flight_data_service.py \
            --api cso --start 2026-01-01 --end 2026-06-30
"""

import argparse
import io
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from foresight.config import settings

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "flights"

CSO_URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/TAM07/CSV/1.0/en"
OPENSKY_URL = "https://opensky-network.org/api/flights/arrival"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
AERODATABOX_HOST = "aerodatabox.p.rapidapi.com"
DUBLIN = ZoneInfo("Europe/Dublin")


def _days(start: date, end: date) -> list[date]:
    """List every date in a range.

    Args:
        start (date): First date.
        end (date): Last date, inclusive.

    Returns:
        list[date]: Dates from ``start`` to ``end``.
    """
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def fetch_cso(start: date, end: date, airport: str = "Dublin") -> pd.DataFrame:
    """Fetch monthly passenger numbers for an Irish airport from CSO table TAM07.

    Args:
        start (date): First day of the range. Its whole month is included.
        end (date): Last day of the range, inclusive. Its whole month is included.
        airport (str): CSO airport name, e.g. "Dublin" or "Cork". Defaults to "Dublin".

    Returns:
        pandas.DataFrame: One row per month, country, direction and flight type, with
        columns ``year``, ``month``, ``airport``, ``country``, ``direction``,
        ``flight_type`` and ``passengers_thousands``.

    Raises:
        httpx.HTTPStatusError: If the CSO request fails.
    """
    response = httpx.get(CSO_URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.content.decode("utf-8-sig")))

    df = df[
        (df["Statistic Label"] == "Passengers") & (df["Airports in Ireland"] == airport)
    ]
    dates = pd.to_datetime(df["Month"], format="%Y %B")
    df = pd.DataFrame(
        {
            "year": dates.dt.year,
            "month": dates.dt.month,
            "airport": df["Airports in Ireland"],
            "country": df["Country"],
            "direction": df["Direction"],
            "flight_type": df["Flight Type"],
            "passengers_thousands": df["VALUE"],
        }
    )
    first_month = pd.Timestamp(start).replace(day=1)
    return df[(dates >= first_month) & (dates <= pd.Timestamp(end))]


def fetch_opensky(start: date, end: date, airport: str = "EIDW") -> pd.DataFrame:
    """Fetch individual flights arriving at an airport from OpenSky.

    Args:
        start (date): First day of the range (Dublin time).
        end (date): Last day of the range, inclusive (Dublin time).
        airport (str): ICAO airport code. Defaults to "EIDW" (Dublin).

    Returns:
        pandas.DataFrame: One row per flight with OpenSky's fields; ``firstSeen``,
        ``lastSeen`` and ``arrival_time`` are in Dublin time. Empty if there were no
        flights.

    Raises:
        httpx.HTTPStatusError: If authentication or a request fails.
    """
    token = httpx.post(
        OPENSKY_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.opensky_client_id,
            "client_secret": settings.opensky_client_secret,
        },
        timeout=30,
    )
    token.raise_for_status()
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

    rows = []
    for day in _days(start, end):
        # Midnight to midnight in Dublin; 23 or 25 hours on clock-change days.
        begin = datetime.combine(day, time.min, DUBLIN)
        end_of_day = datetime.combine(day + timedelta(days=1), time.min, DUBLIN)
        response = httpx.get(
            OPENSKY_URL,
            params={
                "airport": airport,
                "begin": int(begin.timestamp()),
                "end": int(end_of_day.timestamp()),
            },
            headers=headers,
            timeout=60,
        )
        if response.status_code == 404:  # no flights that day
            continue
        response.raise_for_status()
        rows.extend(response.json())

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("firstSeen", "lastSeen"):
        df[col] = pd.to_datetime(df[col], unit="s", utc=True).dt.tz_convert(DUBLIN)
    df["arrival_time"] = df["lastSeen"]
    return df


def fetch_aerodatabox(start: date, end: date, airport: str = "DUB") -> pd.DataFrame:
    """Fetch scheduled flights arriving at an airport from AeroDataBox (via RapidAPI).

    Each day costs about 4 API units; the free plan has 400 a month.

    Args:
        start (date): First day of the range (airport local time).
        end (date): Last day of the range, inclusive (airport local time).
        airport (str): IATA airport code. Defaults to "DUB" (Dublin).

    Returns:
        pandas.DataFrame: One row per flight, with columns ``flight_number``,
        ``airline``, ``aircraft_model``, ``origin_iata``, ``origin_name``,
        ``origin_country``, ``status`` and ``arrival_time`` (scheduled, in Dublin
        time). Empty if there were no flights.

    Raises:
        httpx.HTTPStatusError: If a request fails.
    """
    headers = {
        "X-RapidAPI-Key": settings.xrapidapi_key,
        "X-RapidAPI-Host": AERODATABOX_HOST,
    }
    params = {
        "direction": "Arrival",
        "withCancelled": "false",
        "withCodeshared": "false",
        "withCargo": "false",
        "withPrivate": "false",
        "withLocation": "false",
    }

    rows = []
    for day in _days(start, end):
        # The API allows at most 12 hours per request.
        midnight = datetime.combine(day, time.min)
        for window_start in (midnight, midnight + timedelta(hours=12)):
            window_end = window_start + timedelta(hours=11, minutes=59)
            response = httpx.get(
                f"https://{AERODATABOX_HOST}/flights/airports/iata/{airport}"
                f"/{window_start:%Y-%m-%dT%H:%M}/{window_end:%Y-%m-%dT%H:%M}",
                params=params,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            if response.status_code == 204:  # no flights in this window
                continue
            for item in response.json().get("arrivals", []):
                move = item.get("movement") or {}
                origin = move.get("airport") or {}
                rows.append(
                    {
                        "flight_number": item.get("number"),
                        "airline": (item.get("airline") or {}).get("name"),
                        "aircraft_model": (item.get("aircraft") or {}).get("model"),
                        "origin_iata": origin.get("iata"),
                        "origin_name": origin.get("name"),
                        "origin_country": origin.get("countryCode"),
                        "status": item.get("status"),
                        "arrival_time": (move.get("scheduledTime") or {}).get("utc"),
                    }
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # A delayed flight near a window edge can be returned twice.
    df = df.drop_duplicates(["flight_number", "arrival_time", "origin_iata"])
    df["arrival_time"] = pd.to_datetime(df["arrival_time"], utc=True).dt.tz_convert(
        DUBLIN
    )
    return df


FETCHERS = {
    "cso": fetch_cso,
    "opensky": fetch_opensky,
    "aerodatabox": fetch_aerodatabox,
}


def main() -> None:
    """Fetch the chosen APIs for a date range and save a CSV for each."""
    parser = argparse.ArgumentParser(
        description="Fetch Dublin flight data and save CSVs."
    )
    parser.add_argument("--api", nargs="+", choices=FETCHERS, default=list(FETCHERS))
    parser.add_argument(
        "--start", type=date.fromisoformat, required=True, help="YYYY-MM-DD"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="YYYY-MM-DD, defaults to --start"
    )
    args = parser.parse_args()
    end = args.end or args.start

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for api in args.api:
        df = FETCHERS[api](args.start, end)
        path = OUTPUT_DIR / f"{api}_{args.start}_{end}.csv"
        df.to_csv(path, index=False)
        print(f"[{api}] {len(df)} rows saved to {path}")


if __name__ == "__main__":
    main()
