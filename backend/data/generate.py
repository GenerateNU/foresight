"""Write synthetic Guestline exports in the same format as the real Rezlynx CSVs.

Every value is made up. Guest columns are kept, filled with placeholders, so
parsers can be tested on dropping them.

usage: python3 data/generate.py
"""

import csv
import random
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent
ROOMS = {"DOUBLE": 5, "DBZ": 2, "TWIN": 2, "SINGLE": 1}
IN_STOCK = sum(ROOMS.values())
NIGHTS = [date(2025, 9, 1) + timedelta(n) for n in range(14)]
VAT = 1.135
STAMP = "%d/%m/%Y %H:%M:%S"
DAY = "%d/%b/%Y"

DNR_HEADER = [
    "Site", "Company", "CompanyName", "Agent", "AgentName", "BookRef",
    "GuestName", "Arrival", "Departure", "OperatorCode", "BookingDate",
    "Nights", "ADRSoldNett", "ADRSoldGross", "ReservationValueNett",
    "ReservationValueGross", "CancelledTimeStamp", "CancelledNights",
    "CancelledRevenueNett", "CancelledRevenueGross", "RatePlan",
    "MarketSegment", "RoomType",
]  # fmt: skip


def money(x: float) -> str:
    """Formats an amount as Guestline does.

    Args:
        x (float): The amount.

    Returns:
        str: It, to two decimals.
    """
    return f"{x:.2f}"


def stay(arrival: date, departure: date) -> list[date]:
    """Lists the nights of a stay.

    Args:
        arrival (date): First night.
        departure (date): The morning after the last night.

    Returns:
        list[date]: Each night.
    """
    return [arrival + timedelta(n) for n in range((departure - arrival).days)]


def make_bookings(rng: random.Random) -> list[dict[str, Any]]:
    """Makes bookings that fit the rooms; about 30% are cancelled and left out.

    Args:
        rng (random.Random): The seeded generator.

    Returns:
        list[dict[str, Any]]: Each booking's stay, rooms and rates.
    """
    live = Counter()
    bookings = []
    for _ in range(400):
        arrival = rng.choice(NIGHTS)
        nights = rng.choice([1, 1, 2, 3])
        departure = min(arrival + timedelta(nights), NIGHTS[-1] + timedelta(1))
        rooms = [rng.choice(list(ROOMS)) for _ in range(rng.choice([1, 1, 1, 2, 3]))]
        need = Counter((t, n) for t in rooms for n in stay(arrival, departure))
        if any(live[k] + c > ROOMS[k[0]] for k, c in need.items()):
            continue
        cancelled = rng.random() < 0.3
        if not cancelled:
            live.update(need)
        lead = timedelta(days=rng.randint(0, 90), minutes=rng.randint(0, 1439))
        bookings.append(
            {
                "arrival": arrival,
                "departure": departure,
                "booked_at": datetime.combine(arrival, time()) - lead,
                "rooms": [(t, round(rng.uniform(80, 220), 2)) for t in rooms],
                "cancelled": cancelled,
            }
        )
    return bookings


def write(name: str, header: list[str], rows: list[list[str]]) -> None:
    """Writes a CSV as Guestline exports it: quoted, with a byte-order mark.

    Args:
        name (str): The file name, in this folder.
        header (list[str]): The column names.
        rows (list[list[str]]): The rows.
    """
    with open(OUT / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    """Writes the synthetic Daily New Reservations export."""
    rng = random.Random(0)
    bookings = make_bookings(rng)
    dnr = []
    total = Counter()
    for i, b in enumerate(bookings, start=1):
        nights = stay(b["arrival"], b["departure"])
        arrival, departure = b["arrival"].strftime(DAY), b["departure"].strftime(DAY)
        booked_at = b["booked_at"].strftime(STAMP)
        for n, (room_type, rate) in enumerate(b["rooms"], start=1):
            ref = f"BK{100000 + i}/{n}"
            value = rate * len(nights)
            if b["cancelled"]:
                # Cancellations aren't written any more; draw as their times
                # did, so the bookings file stays as it was.
                if rng.random() >= 0.1:
                    rng.random()
                continue
            single = room_type == "SINGLE"
            plan = "BAR_RO_SGL" if single else rng.choice(["BAR_RO", "BAR_RO_DB"])
            dnr.append([
                "Synthetic Hotel", "", "", "", "", ref, f"Synthetic Guest {i}",
                arrival, departure, "SYSTEM", booked_at, str(len(nights)),
                money(rate), money(rate * VAT), money(value), money(value * VAT),
                "", "0", "0.00", "0.00", plan, "LEISURE", room_type,
            ])  # fmt: skip
            for night in nights:
                total[night] += 1
    dnr.sort(key=lambda r: datetime.strptime(r[10], STAMP))

    write("DailyNewReservations.csv", DNR_HEADER, dnr)
    occupancy = sum(total.values()) / (IN_STOCK * len(NIGHTS))
    print(f"{len(dnr)} live rooms, {occupancy:.0%} occupancy")


if __name__ == "__main__":
    main()
