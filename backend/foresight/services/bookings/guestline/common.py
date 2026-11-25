import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

PARSE_ERRORS = (ValueError, csv.Error, UnicodeDecodeError)
_MONEY_LIMIT = 10**8


@dataclass(frozen=True)
class Parsed:
    """A parsed Guestline export.

    Attributes:
        rows (list[dict[str, Any]]): One dict per readable row.
        skipped (int): Bad rows left out.
    """

    rows: list[dict[str, Any]]
    skipped: int


def parse_rows(
    content: bytes,
    report: str,
    columns: list[str],
    to_row: Callable[[dict[str, str]], dict[str, Any]],
) -> Parsed:
    """Reads a Guestline row-per-record CSV export.

    Only the columns a report needs are read, so guest details (names,
    profile refs, operators, free-text company and cancel reason) are never
    copied. A bad row is skipped and counted: a stray quote in a guest name
    shifts the fields, leaving some missing or extra. A header-only file is a
    quiet day; every row failing means the format changed.

    Args:
        content (bytes): The uploaded file, with Guestline's byte-order mark.
        report (str): The report's name, for messages.
        columns (list[str]): The columns the report needs.
        to_row (Callable[[dict[str, str]], dict[str, Any]]): Turns one CSV
            line into a row; raises ValueError for a bad line.

    Returns:
        Parsed: The rows read, and how many were skipped.

    Raises:
        ValueError: A needed column is missing, or no row is readable.
    """
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    missing = [c for c in columns if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"not a {report} export, missing columns: {missing}")
    rows, skipped = [], 0
    for line in reader:
        try:
            if None in line or None in line.values():
                raise ValueError("wrong number of fields")
            rows.append(to_row(line))
        except (ValueError, ArithmeticError) as exc:
            skipped += 1
            logger.warning("%s line %d skipped: %s", report, reader.line_num, exc)
    if skipped and not rows:
        raise ValueError(f"no readable rows in the {report} export")
    return Parsed(rows, skipped)


def optional(value: str, limit: int) -> str | None:
    """Reads an optional text value.

    Args:
        value (str): The raw value.
        limit (int): The column's length.

    Returns:
        str | None: The trimmed value, or None if it's empty.

    Raises:
        ValueError: It's longer than the column.
    """
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"value is longer than {limit} characters")
    return value or None


def required(value: str, limit: int) -> str:
    """Reads a required text value.

    Args:
        value (str): The raw value.
        limit (int): The column's length.

    Returns:
        str: The trimmed value.

    Raises:
        ValueError: It's empty, or longer than the column.
    """
    text = optional(value, limit)
    if text is None:
        raise ValueError("a required value is empty")
    return text


def money(value: str) -> Decimal:
    """Reads an amount that fits a Numeric(10, 2) column.

    Args:
        value (str): The raw value.

    Returns:
        Decimal: The amount.

    Raises:
        ValueError: It isn't finite or doesn't fit the column.
        ArithmeticError: It isn't a number.
    """
    amount = Decimal(value)
    if not amount.is_finite() or abs(amount) >= _MONEY_LIMIT:
        raise ValueError("amount is out of range")
    return amount


def timestamp(value: str) -> datetime:
    """Reads a Guestline timestamp, e.g. 05/06/2025 16:32:00.

    Args:
        value (str): The raw value.

    Returns:
        datetime: The moment, in the hotel's local time.

    Raises:
        ValueError: It isn't in that format.
    """
    return datetime.strptime(value, "%d/%m/%Y %H:%M:%S")


def day(value: str) -> date:
    """Reads a Guestline date, e.g. 03/Sep/2025.

    Args:
        value (str): The raw value.

    Returns:
        date: The date.

    Raises:
        ValueError: It isn't in that format.
    """
    return datetime.strptime(value, "%d/%b/%Y").date()
