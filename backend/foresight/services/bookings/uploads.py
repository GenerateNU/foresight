import csv
import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from foresight.database.enums import JobKind
from foresight.database.models.hotel import Hotel
from foresight.repository import booking as booking_repo
from foresight.repository.upsert import Outcome
from foresight.services.bookings.guestline import cancellations, reservations
from foresight.services.bookings.guestline.common import PARSE_ERRORS, Parsed
from foresight.services.errors import InvalidRequestError

type Parse = Callable[[bytes], Parsed]
type Save = Callable[
    [AsyncSession, Hotel, Sequence[Mapping[str, Any]]],
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
    """

    kind: JobKind
    name: str
    columns: Sequence[str]
    date_field: str
    parse: Parse
    save: Save


async def _save_reservations(
    session: AsyncSession, hotel: Hotel, rows: Sequence[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Saves a chunk of bookings for a hotel; does not commit.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        rows (Sequence[Mapping[str, Any]]): Parsed bookings.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
    return await booking_repo.upsert_bookings(
        session, [{**row, "hotel_id": hotel.id} for row in rows]
    )


async def _save_cancellations(
    session: AsyncSession, hotel: Hotel, rows: Sequence[Mapping[str, Any]]
) -> dict[Outcome, int]:
    """Saves a chunk of cancellations for a hotel; does not commit.

    Args:
        session (AsyncSession): The database session.
        hotel (Hotel): The hotel.
        rows (Sequence[Mapping[str, Any]]): Parsed cancellations.

    Returns:
        dict[Outcome, int]: How many rows were new, updated and unchanged.
    """
    return await booking_repo.upsert_cancellations(
        session, [{**row, "hotel_id": hotel.id} for row in rows]
    )


REPORTS: tuple[Report, ...] = (
    Report(
        JobKind.RESERVATIONS,
        reservations.REPORT,
        reservations.COLUMNS,
        "booked_at",
        reservations.parse,
        _save_reservations,
    ),
    Report(
        JobKind.CANCELLATIONS,
        cancellations.REPORT,
        cancellations.COLUMNS,
        "cancelled_at",
        cancellations.parse,
        _save_cancellations,
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
        params (dict[str, Any]): The upload record, stored on the job.
    """

    name: str
    report: Report
    rows: list[dict[str, Any]]
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
        parsed = report.parse(content)
    except PARSE_ERRORS as exc:
        raise InvalidRequestError(f"could not import {name}: {exc}") from exc
    rows, skipped = parsed.rows, parsed.skipped
    days = [_day(row[report.date_field]) for row in rows]
    params: dict[str, Any] = {
        "file": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "rows": len(rows),
        "skipped": skipped,
        "first_date": min(days).isoformat() if days else None,
        "last_date": max(days).isoformat() if days else None,
    }
    return ParsedFile(name, report, rows, params)


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
