"""Read Guestline's Daily New Reservations and Cancellations CSV exports.

Each row becomes a dictionary ready to save. Only the columns we need are read,
so guest details (names, profile refs, operators, free-text company and cancel
reason) are never copied. A bad row is skipped and counted. A file missing a
column we need is rejected.

Never touches the database; `services/ingest/bookings.py` saves the rows.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# What a file that can't be read at all raises.
PARSE_ERRORS = (ValueError, csv.Error, UnicodeDecodeError)

_MONEY_LIMIT = 10**8  # money columns are Numeric(10, 2)

BOOKING_COLUMNS = [
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
CANCELLATION_COLUMNS = [
    "CancelRef",
    "Ref",
    "BookingCreatedDate",
    "CancelDate",
    "CancelReasonCode",
    "ArrivalDate",
    "DepartureDate",
    "EstimatedRevenue",
]


@dataclass(frozen=True)
class Parsed:
    rows: list[dict[str, Any]]
    skipped: int  # bad rows left out


def parse_bookings(content: bytes) -> Parsed:
    return _parse(content, "Daily New Reservations", BOOKING_COLUMNS, _booking)


def parse_cancellations(content: bytes) -> Parsed:
    return _parse(content, "Cancellations", CANCELLATION_COLUMNS, _cancellation)


def _booking(line: dict[str, str]) -> dict[str, Any]:
    booking = {
        "book_ref": _required(line["BookRef"], 32),
        "booked_at": _timestamp(line["BookingDate"]),
        "arrival": _day(line["Arrival"]),
        "departure": _day(line["Departure"]),
        "nights": int(line["Nights"]),
        "room_type_code": _required(line["RoomType"], 32),
        # Company is a code; CompanyName is free text.
        "company_code": _optional(line["Company"], 64),
        "agent_code": _optional(line["Agent"], 64),
        "adr_nett": _money(line["ADRSoldNett"]),
        "value_nett": _money(line["ReservationValueNett"]),
        "rate_plan": _optional(line["RatePlan"], 64),
        "market_segment": _optional(line["MarketSegment"], 64),
    }
    if booking["departure"] <= booking["arrival"]:
        raise ValueError("departure is not after arrival")
    if booking["nights"] not in range(2**31):
        raise ValueError("nights is out of range")
    return booking


def _cancellation(line: dict[str, str]) -> dict[str, Any]:
    cancellation = {
        "cancel_ref": _required(line["CancelRef"], 32),
        "book_ref": _required(line["Ref"], 32),
        "booked_at": _timestamp(line["BookingCreatedDate"]),
        "cancelled_at": _timestamp(line["CancelDate"]),
        "reason_code": _optional(line["CancelReasonCode"], 32),
        "arrival": _day(line["ArrivalDate"]),
        "departure": _day(line["DepartureDate"]),
        "lost_revenue": _money(line["EstimatedRevenue"]),
    }
    if cancellation["departure"] <= cancellation["arrival"]:
        raise ValueError("departure is not after arrival")
    if cancellation["cancelled_at"] < cancellation["booked_at"]:
        raise ValueError("cancelled before it was booked")
    return cancellation


def _parse(
    content: bytes,
    report: str,
    columns: list[str],
    to_row: Callable[[dict[str, str]], dict[str, Any]],
) -> Parsed:
    # utf-8-sig drops the byte-order mark Guestline puts at the start of the file.
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    missing = [c for c in columns if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"not a {report} export, missing columns: {missing}")

    rows, skipped = [], 0
    for line in reader:
        try:
            # A stray quote in a guest name shifts the fields, leaving some
            # missing (None values) or extra (a None key).
            if None in line or None in line.values():
                raise ValueError("wrong number of fields")
            rows.append(to_row(line))
        except (ValueError, ArithmeticError) as exc:  # ArithmeticError: bad Decimal
            skipped += 1
            logger.warning("%s line %d skipped: %s", report, reader.line_num, exc)
    # A header-only file is a quiet day; every row failing is a format change.
    if skipped and not rows:
        raise ValueError(f"no readable rows in the {report} export")
    return Parsed(rows, skipped)


def _optional(value: str, limit: int) -> str | None:
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"value is longer than {limit} characters")
    return value or None


def _required(value: str, limit: int) -> str:
    text = _optional(value, limit)
    if text is None:
        raise ValueError("a required value is empty")
    return text


def _money(value: str) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or abs(amount) >= _MONEY_LIMIT:
        raise ValueError("amount is out of range")
    return amount


def _timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%d/%m/%Y %H:%M:%S")  # 05/06/2025 16:32:00


def _day(value: str) -> date:
    return datetime.strptime(value, "%d/%b/%Y").date()  # 03/Sep/2025
