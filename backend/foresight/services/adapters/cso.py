"""CSO adapter: monthly passenger numbers for Irish airports (table TAM07).

Not persisted yet: `flight_arrivals` is one row per airport per day and CSO
reports per month. Kept as an adapter until a monthly table or a daily
spreading rule is decided. No DB writes.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


URL = (
    "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset"
    "/TAM07/CSV/1.0/en"
)


@dataclass(frozen=True, slots=True)
class MonthlyPassengers:
    month: date  # first of the month
    airport: str  # CSO name, e.g. "Dublin"
    country: str
    direction: str
    flight_type: str
    passengers_thousands: float | None


async def fetch_monthly_passengers(
    http: httpx.AsyncClient,
    start: date,
    end: date,
    *,
    airport: str = "Dublin",
) -> list[MonthlyPassengers]:
    """Passenger rows for every month touching `start`..`end`."""
    response = await http.get(URL, follow_redirects=True)
    response.raise_for_status()
    first_month = start.replace(day=1)
    out = []
    for row in csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))):
        if row["Statistic Label"] != "Passengers":
            continue
        if row["Airports in Ireland"] != airport:
            continue
        month = datetime.strptime(row["Month"], "%Y %B").date()
        if not first_month <= month <= end:
            continue
        out.append(
            MonthlyPassengers(
                month=month,
                airport=airport,
                country=row["Country"],
                direction=row["Direction"],
                flight_type=row["Flight Type"],
                passengers_thousands=float(row["VALUE"]) if row["VALUE"] else None,
            )
        )
    return out
