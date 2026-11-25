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
    """Parses a Cancellations export: one row per room cancelled.

    Args:
        content (bytes): The uploaded file.

    Returns:
        Parsed: One cancellation per readable row.

    Raises:
        ValueError: A needed column is missing, or no row is readable.
    """
    return parse_rows(content, REPORT, COLUMNS, _row)


def _row(line: dict[str, str]) -> dict[str, Any]:
    """Reads one cancelled room.

    Args:
        line (dict[str, str]): One CSV line.

    Returns:
        dict[str, Any]: The cancellation's columns.

    Raises:
        ValueError: A value is missing or malformed, the stay is empty, or it
            was cancelled before it was booked.
    """
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
