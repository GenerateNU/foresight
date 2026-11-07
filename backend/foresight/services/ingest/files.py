"""Uploaded hotel CSVs: work out which report each file is, parse it, save it.

`REPORTS` is the one list of report kinds (decision 0052). A file is a kind
when its header holds every column that kind needs; matching none or more
than one is an error. Adding a report is an adapter plus one entry here.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from foresight.database.enums import JobKind
from foresight.services.errors import InvalidRequestError
from foresight.services.ingest import actual_forecast, bookings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel
    from foresight.repository.upsert import Outcome

    type Parse = Callable[[bytes], tuple[list[dict[str, Any]], int, dict[str, Any]]]
    type Save = Callable[
        [AsyncSession, Hotel, Sequence[Mapping[str, Any]], Mapping[str, Any]],
        Awaitable[dict[Outcome, int]],
    ]

# Rows saved, and committed, per chunk.
CHUNK_ROWS = 5_000


@dataclass(frozen=True, slots=True)
class Report:
    kind: JobKind
    name: str  # as Guestline titles the report
    columns: Sequence[str]  # every one must be in the header
    date_field: str  # the row field the export is filtered by
    parse: Parse
    save: Save
    # What a malformed file raises while parsing.
    errors: tuple[type[Exception], ...]


REPORTS: tuple[Report, ...] = (
    Report(
        JobKind.ACTUAL_FORECAST,
        "Actual & Forecast",
        actual_forecast.COLUMNS,
        actual_forecast.DATE_FIELD,
        actual_forecast.parse,
        actual_forecast.save,
        actual_forecast.PARSE_ERRORS,
    ),
    Report(
        JobKind.RESERVATIONS,
        "Daily New Reservations",
        bookings.RESERVATION_COLUMNS,
        bookings.RESERVATION_DATE_FIELD,
        bookings.parse_reservations,
        bookings.save_reservations,
        bookings.PARSE_ERRORS,
    ),
    Report(
        JobKind.CANCELLATIONS,
        "Cancellations",
        bookings.CANCELLATION_COLUMNS,
        bookings.CANCELLATION_DATE_FIELD,
        bookings.parse_cancellations,
        bookings.save_cancellations,
        bookings.PARSE_ERRORS,
    ),
)
_BY_KIND = {report.kind: report for report in REPORTS}
FILE_KINDS = frozenset(_BY_KIND)


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """One uploaded file, parsed and held in memory until its job runs."""

    name: str
    report: Report
    rows: list[dict[str, Any]]
    extra: dict[str, Any]  # what saving needs beyond the rows
    params: dict[str, Any]  # the upload record, stored on the job


def parse_files(files: Sequence[tuple[str, bytes]]) -> list[ParsedFile]:
    """Recognise and parse every file before anything is queued.

    Raises:
        InvalidRequestError: Naming the first file that matches no report,
            more than one, or doesn't parse.
    """
    return [_parse_file(name, content) for name, content in files]


def report_for(kind: JobKind) -> Report:
    return _BY_KIND[kind]


def chunks(rows: Sequence[Any]) -> list[Sequence[Any]]:
    return [rows[i : i + CHUNK_ROWS] for i in range(0, len(rows), CHUNK_ROWS)]


def _parse_file(name: str, content: bytes) -> ParsedFile:
    report = _recognise(name, content)
    try:
        rows, skipped, extra = report.parse(content)
    except report.errors as exc:
        raise InvalidRequestError(f"could not import {name}: {exc}") from exc
    params: dict[str, Any] = {
        "file": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "rows": len(rows),
        "skipped": skipped,
        "first_date": None,
        "last_date": None,
    }
    days = [_day(row[report.date_field]) for row in rows]
    if days:
        params["first_date"] = min(days).isoformat()
        params["last_date"] = max(days).isoformat()
    return ParsedFile(name, report, rows, extra, params)


def _recognise(name: str, content: bytes) -> Report:
    header = set(_header(name, content))
    matches = [r for r in REPORTS if set(r.columns) <= header]
    if not matches:
        known = ", ".join(r.name for r in REPORTS)
        raise InvalidRequestError(f"{name} is not a known report (expected {known})")
    if len(matches) > 1:
        names = ", ".join(r.name for r in matches)
        raise InvalidRequestError(f"{name} matches more than one report: {names}")
    return matches[0]


def _header(name: str, content: bytes) -> list[str]:
    try:
        # utf-8-sig drops the byte-order mark Guestline puts at the start.
        first = content.decode("utf-8-sig").splitlines()[:1]
        return [c.strip() for c in next(csv.reader(first), [])]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise InvalidRequestError(f"could not read {name} as CSV: {exc}") from exc


def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value
