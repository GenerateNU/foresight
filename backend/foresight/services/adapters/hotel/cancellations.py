"""Guestline Cancellations export: one row per room cancelled.

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

REPORT = "Cancellations"

COLUMNS = [
    "CancelRef",
    "Ref",
    "BookingCreatedDate",
    "CancelDate",
    "CancelReasonCode",
    "ArrivalDate",
    "DepartureDate",
    "EstimatedRevenue",
]


def parse(content: bytes) -> Parsed:
    return parse_rows(content, REPORT, COLUMNS, _row)


def _row(line: dict[str, str]) -> dict[str, Any]:
    cancellation = {
        "cancel_ref": required(line["CancelRef"], 32),
        "book_ref": required(line["Ref"], 32),
        "booked_at": timestamp(line["BookingCreatedDate"]),
        "cancelled_at": timestamp(line["CancelDate"]),
        "reason_code": optional(line["CancelReasonCode"], 32),
        "arrival": day(line["ArrivalDate"]),
        "departure": day(line["DepartureDate"]),
        "lost_revenue": money(line["EstimatedRevenue"]),
    }
    if cancellation["departure"] <= cancellation["arrival"]:
        raise ValueError("departure is not after arrival")
    if cancellation["cancelled_at"] < cancellation["booked_at"]:
        raise ValueError("cancelled before it was booked")
    return cancellation
