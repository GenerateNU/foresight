"""Guestline Daily New Reservations export: one row per room booked.

Never touches the database; `services/ingest/bookings.py` saves the rows.
"""

from __future__ import annotations

from typing import Any

from foresight.services.adapters.hotel.common import (
    PARSE_ERRORS,
    Parsed,
    day,
    money,
    optional,
    parse_rows,
    required,
    timestamp,
)

__all__ = ["COLUMNS", "PARSE_ERRORS", "REPORT", "Parsed", "parse"]

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
    return parse_rows(content, REPORT, COLUMNS, _row)


def _row(line: dict[str, str]) -> dict[str, Any]:
    booking = {
        "book_ref": required(line["BookRef"], 32),
        "booked_at": timestamp(line["BookingDate"]),
        "arrival": day(line["Arrival"]),
        "departure": day(line["Departure"]),
        "nights": int(line["Nights"]),
        "room_type_code": required(line["RoomType"], 32),
        # Company is a code; CompanyName is free text.
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
