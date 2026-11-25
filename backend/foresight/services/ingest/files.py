import csv
import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import JobKind
from foresight.database.models.hotel import Hotel
from foresight.repository.upsert import Outcome
from foresight.services.errors import InvalidRequestError
from foresight.services.ingest import bookings

type Parse = Callable[[bytes], tuple[list[dict[str, Any]], int, dict[str, Any]]]
type Save = Callable[
    [AsyncSession, Hotel, Sequence[Mapping[str, Any]], Mapping[str, Any]],
    Awaitable[dict[Outcome, int]],
]

CHUNK_ROWS = 5_000


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Reports                          │
#          ╰──────────────────────────────────────────────────────────╯


@dataclass(frozen=True, slots=True)
class Report:
    """One kind of uploaded Guestline report.

    A file is this kind when its header holds every one of `columns`.

    Attributes:
        kind (JobKind): The job that saves it.
        name (str): As Guestline titles the report.
        columns (Sequence[str]): The columns its header must hold.
        date_field (str): The row field the export is filtered by.
        parse (Parse): Reads a file into rows.
        save (Save): Saves a chunk of rows.
        errors (tuple[type[Exception], ...]): What a malformed file raises.
    """

    kind: JobKind
    name: str
    columns: Sequence[str]
    date_field: str
    parse: Parse
    save: Save
    errors: tuple[type[Exception], ...]


REPORTS: tuple[Report, ...] = (
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
FILE_KINDS = frozenset(report.kind for report in REPORTS)


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """One uploaded file, parsed and held in memory until its job runs.

    Attributes:
        name (str): The file's name.
        report (Report): Which report it is.
        rows (list[dict[str, Any]]): Its parsed rows.
        extra (dict[str, Any]): What saving needs beyond the rows.
        params (dict[str, Any]): The upload record, stored on the job.
    """

    name: str
    report: Report
    rows: list[dict[str, Any]]
    extra: dict[str, Any]
    params: dict[str, Any]


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Parsing                          │
#          ╰──────────────────────────────────────────────────────────╯


def parse_files(files: Sequence[tuple[str, bytes]]) -> list[ParsedFile]:
    """Recognises and parses every file before anything is queued.

    Args:
        files (Sequence[tuple[str, bytes]]): Each file's name and content.

    Returns:
        list[ParsedFile]: The files, in upload order.

    Raises:
        InvalidRequestError: Naming the first file that matches no report,
            more than one, or doesn't parse.
    """
    return [_parse_file(name, content) for name, content in files]


def chunks(rows: Sequence[Any]) -> list[Sequence[Any]]:
    """Splits rows into chunks saved, and committed, one at a time.

    Args:
        rows (Sequence[Any]): The rows.

    Returns:
        list[Sequence[Any]]: Chunks of at most CHUNK_ROWS rows.
    """
    return [rows[i : i + CHUNK_ROWS] for i in range(0, len(rows), CHUNK_ROWS)]


def _parse_file(name: str, content: bytes) -> ParsedFile:
    """Recognises and parses one file, and records what was uploaded.

    Args:
        name (str): The file's name.
        content (bytes): Its content.

    Returns:
        ParsedFile: The parsed file.

    Raises:
        InvalidRequestError: It matches no report, more than one, or doesn't
            parse.
    """
    report = _recognise(name, content)
    try:
        rows, skipped, extra = report.parse(content)
    except report.errors as exc:
        raise InvalidRequestError(f"could not import {name}: {exc}") from exc
    days = [_day(row[report.date_field]) for row in rows]
    params: dict[str, Any] = {
        "file": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "rows": len(rows),
        "skipped": skipped,
        "first_date": min(days).isoformat() if days else None,
        "last_date": max(days).isoformat() if days else None,
    }
    return ParsedFile(name, report, rows, extra, params)


def _recognise(name: str, content: bytes) -> Report:
    """Works out which report a file is from its header.

    Args:
        name (str): The file's name.
        content (bytes): Its content.

    Returns:
        Report: The one report whose columns the header holds.

    Raises:
        InvalidRequestError: It matches no report, or more than one.
    """
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
    """Reads a CSV's header, dropping the byte-order mark Guestline adds.

    Args:
        name (str): The file's name.
        content (bytes): Its content.

    Returns:
        list[str]: The column names.

    Raises:
        InvalidRequestError: It isn't readable as CSV.
    """
    try:
        first = content.decode("utf-8-sig").splitlines()[:1]
        return [c.strip() for c in next(csv.reader(first), [])]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise InvalidRequestError(f"could not read {name} as CSV: {exc}") from exc


def _day(value: date | datetime) -> date:
    """Takes the date of a date or a timestamp.

    Args:
        value (date | datetime): The value.

    Returns:
        date: Its date.
    """
    return value.date() if isinstance(value, datetime) else value
