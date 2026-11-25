from typing import Any

from foresight.services.bookings.guestline.common import (
    Parsed,
    day,
    money,
    optional,
    parse_rows,
    required,
    timestamp,
)

REPORT = "Daily New Reservations"
COLUMNS = [
    "BookRef",
    "BookingDate",
    "Arrival",
    "Departure",
    "Nights",
    "RoomType",
    "Company",
    "Agent",
    "ADRSoldNett",
    "ReservationValueNett",
    "RatePlan",
    "MarketSegment",
]


def parse(content: bytes) -> Parsed:
    """Parses a Daily New Reservations export: one row per room booked.

    Args:
        content (bytes): The uploaded file.

    Returns:
        Parsed: One booking per readable row.

    Raises:
        ValueError: A needed column is missing, or no row is readable.
    """
    return parse_rows(content, REPORT, COLUMNS, _row)


def _row(line: dict[str, str]) -> dict[str, Any]:
    """Reads one booked room; `Company` is a code, `CompanyName` free text.

    Args:
        line (dict[str, str]): One CSV line.

    Returns:
        dict[str, Any]: The booking's columns.

    Raises:
        ValueError: A value is missing or malformed, or the stay is empty.
    """
    booking = {
        "book_ref": required(line["BookRef"], 32),
        "booked_at": timestamp(line["BookingDate"]),
        "arrival": day(line["Arrival"]),
        "departure": day(line["Departure"]),
        "nights": int(line["Nights"]),
        "room_type_code": required(line["RoomType"], 32),
        "company_code": optional(line["Company"], 64),
        "agent_code": optional(line["Agent"], 64),
        "adr_nett": money(line["ADRSoldNett"]),
        "value_nett": money(line["ReservationValueNett"]),
        "rate_plan": optional(line["RatePlan"], 64),
        "market_segment": optional(line["MarketSegment"], 64),
    }
    if booking["departure"] <= booking["arrival"]:
        raise ValueError("departure is not after arrival")
    if booking["nights"] not in range(2**31):
        raise ValueError("nights is out of range")
    return booking
