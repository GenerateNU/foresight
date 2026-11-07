"""Shared reading for Guestline row-per-record CSV exports.

Only the columns a report needs are read, so guest details (names, profile
refs, operators, free-text company and cancel reason) are never copied. A bad
row is skipped and counted. A file missing a column we need is rejected.
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


@dataclass(frozen=True)
class Parsed:
    rows: list[dict[str, Any]]
    skipped: int  # bad rows left out


def parse_rows(
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


def optional(value: str, limit: int) -> str | None:
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"value is longer than {limit} characters")
    return value or None


def required(value: str, limit: int) -> str:
    text = optional(value, limit)
    if text is None:
        raise ValueError("a required value is empty")
    return text


def money(value: str) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or abs(amount) >= _MONEY_LIMIT:
        raise ValueError("amount is out of range")
    return amount


def timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%d/%m/%Y %H:%M:%S")  # 05/06/2025 16:32:00


def day(value: str) -> date:
    return datetime.strptime(value, "%d/%b/%Y").date()  # 03/Sep/2025
