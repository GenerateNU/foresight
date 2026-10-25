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
CN_HEADER = [
    "CancelRef", "CancelDate", "CancelReasonCode", "Surname", "Company",
    "Agent", "Ref", "ArrivalDate", "DepartureDate", "ProfileRef", "Operator",
    "EstimatedRevenue", "CancelReason", "BookingCreatedDate",
]  # fmt: skip
AF_HEADER = [
    "Date", "DayOfWeek", "Avail", "Total", "Indv", "Multi", "Blocks", "Occ",
    "Ad", "Ch", "Inf", "Accomm", "FB", "Other", "NonRevenue", "TotalRevenue",
    "GrandTotal", "CumulativeAccomm", "CumulativeFB", "CumulativeOther",
    "CumulativeTotalRevenue", "CumulativeNonRevenue", "CumulativeGrandTotal",
    "ARR", "APR", "Yield", "Blked", "ROOS", "DFS", "Waitlist", "InStock",
    "RatePlanRevenue",
]  # fmt: skip


def money(x):
    return f"{x:.2f}"


def stay(arrival, departure):
    return [arrival + timedelta(n) for n in range((departure - arrival).days)]


def make_bookings(rng):
    """Bookings that fit the rooms; about 30% are later cancelled."""
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


def cancel_time(rng, booking):
    arrival = datetime.combine(booking["arrival"], time())
    if rng.random() < 0.1:
        return "NO_SHOW", arrival + timedelta(days=1, hours=10)
    return "GDE", booking["booked_at"] + (arrival - booking["booked_at"]) * rng.random()


def write(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(header)
        w.writerows(rows)


def read(name):
    with open(OUT / name, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    rng = random.Random(0)
    bookings = make_bookings(rng)
    dnr, cn = [], []
    total, multi, nett = Counter(), Counter(), Counter()
    for i, b in enumerate(bookings, start=1):
        nights = stay(b["arrival"], b["departure"])
        arrival, departure = b["arrival"].strftime(DAY), b["departure"].strftime(DAY)
        booked_at = b["booked_at"].strftime(STAMP)
        for n, (room_type, rate) in enumerate(b["rooms"], start=1):
            ref = f"BK{100000 + i}/{n}"
            value = rate * len(nights)
            if b["cancelled"]:
                code, at = cancel_time(rng, b)
                cn.append([
                    f"CN{50000 + i}/{n}", at.strftime(STAMP), code, f"Guest{i}",
                    "", "", ref, arrival, departure, f"PF{i:06d}", "SYSTEM",
                    money(value), "", booked_at,
                ])  # fmt: skip
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
                multi[night] += len(b["rooms"]) > 1
                nett[night] += rate
    dnr.sort(key=lambda r: datetime.strptime(r[10], STAMP))
    cn.sort(key=lambda r: datetime.strptime(r[1], STAMP))

    af, cum = [], 0.0
    for night in NIGHTS:
        sold, accomm = total[night], round(nett[night], 2)
        roos = rng.choice([0, 0, 0, 1]) if sold < IN_STOCK else 0
        adults = sold * 2
        cum += accomm
        af.append([
            datetime.combine(night, time()).strftime(STAMP), night.strftime("%A"),
            money(IN_STOCK - sold - roos), str(sold), str(sold - multi[night]),
            str(multi[night]), "0", money(100 * sold / IN_STOCK), str(adults),
            "0", "0", money(accomm), "0.00", "0.00", "0.00", money(accomm),
            money(accomm), money(cum), "0.00", "0.00", money(cum), "0.00",
            money(cum), money(accomm / sold if sold else 0),
            money(accomm / adults if adults else 0), money(accomm / IN_STOCK),
            "0", str(roos), "0", "0", str(IN_STOCK), money(accomm * VAT),
        ])  # fmt: skip

    write("DailyNewReservations.csv", DNR_HEADER, dnr)
    write("Cancellation.csv", CN_HEADER, cn)
    write("Actual & Forecast.csv", AF_HEADER, af)

    rebuilt = Counter()
    for r in read("DailyNewReservations.csv"):
        a, d = (datetime.strptime(r[k], DAY).date() for k in ("Arrival", "Departure"))
        rebuilt.update(stay(a, d))
    for r in read("Actual & Forecast.csv"):
        night = datetime.strptime(r["Date"], STAMP).date()
        assert rebuilt[night] == int(r["Total"]), f"{night}: rebuild != Total"
        assert float(r["Avail"]) >= 0, f"{night}: overbooked"
    for r in read("Cancellation.csv"):
        created, cancelled = (
            datetime.strptime(r[k], STAMP) for k in ("BookingCreatedDate", "CancelDate")
        )
        assert created <= cancelled, f"{r['CancelRef']}: cancelled before booked"
    occupancy = sum(total.values()) / (IN_STOCK * len(NIGHTS))
    print(f"{len(dnr)} live rooms, {len(cn)} cancelled, {occupancy:.0%} occupancy")


if __name__ == "__main__":
    main()
