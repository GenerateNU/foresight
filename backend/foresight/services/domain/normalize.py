import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from foresight.database.enums import DatePrecision, EventCategory, EventStatus, Source

_BRACKETED = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_PRESENTER_TAIL = re.compile(
    r"\s*[-–—:|]?\s*(?:presented|sponsored|brought)\s+by\b.*$", re.I
)
_GUEST_TAIL = re.compile(
    r"\s*\b(?:feat\.?|featuring|w/|with\s+special\s+guests?)\b.*$", re.I
)
_TOUR_TAIL = re.compile(
    r"\s*\b(?:the\s+)?\d{4}(?:[/-]\d{2,4})?\s+\S*\s*tour\b.*$", re.I
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_INITIALISM = re.compile(r"\b(?:[a-z] ){1,}[a-z]\b")
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")


def _strip_accents(text: str) -> str:
    """Removes accents, e.g. "é" to "e".

    Args:
        text (str): The text.

    Returns:
        str: The text without accents.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(title: str) -> str:
    """Reduces a title to the part two sources are likely to agree on.

    Initialisms collapse, so "Fontaines D.C." and "Fontaines DC" match.

    Args:
        title (str): The title.

    Returns:
        str: The normalized title.
    """
    text = _strip_accents(title).lower()
    text = _BRACKETED.sub(" ", text)
    for pattern in (_PRESENTER_TAIL, _GUEST_TAIL, _TOUR_TAIL):
        text = pattern.sub("", text)
    text = _NON_ALNUM.sub(" ", text).strip()
    text = _INITIALISM.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = _LEADING_ARTICLE.sub("", text)
    return " ".join(text.split())


def slugify_city(city: str) -> str:
    """Normalizes a city name, dropping any region, e.g. "Dublin, Ireland".

    Args:
        city (str): The name.

    Returns:
        str: The slug; empty if it has no letters or digits.
    """
    head = city.split(",")[0]
    slug = _NON_ALNUM.sub("-", _strip_accents(head).lower())
    return slug.strip("-")


def dedupe_key(*, title: str, city: str, start_local_date: date) -> str:
    """Builds a stable identity for a real-world event occurrence.

    Every source must land on the same row for the same event. Category is
    left out: two sources routinely disagree on it, and that must not split
    one event into two rows.

    Args:
        title (str): The event's title.
        city (str): Its city.
        start_local_date (date): Its first day, local.

    Returns:
        str: The key.
    """
    basis = (
        f"{normalize_title(title)}|{slugify_city(city)}|{start_local_date.isoformat()}"
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def resolve_timezone(name: str | None) -> tzinfo:
    """Looks up an IANA timezone.

    Args:
        name (str | None): The zone's name.

    Returns:
        tzinfo: The zone; UTC for a missing or unknown one.
    """
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def to_local_date(moment: datetime, timezone: str | None) -> date:
    """Gives the calendar date in the event's own timezone.

    A stay night is local, so a 21:00 event must not drift onto the next
    night because its UTC timestamp crosses midnight.

    Args:
        moment (datetime): The moment; without a zone, UTC.
        timezone (str | None): The event's timezone.

    Returns:
        date: The local date.
    """
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(resolve_timezone(timezone)).date()


def coords_from_geojson(
    location: Sequence[float] | None,
) -> tuple[float | None, float | None]:
    """Reads a GeoJSON point, which is longitude first.

    Args:
        location (Sequence[float] | None): The point.

    Returns:
        tuple[float | None, float | None]: Latitude and longitude; None for
            both if it's missing.
    """
    if not location or len(location) < 2:
        return None, None
    longitude, latitude = float(location[0]), float(location[1])
    return latitude, longitude


@dataclass(slots=True)
class NormalizedEvent:
    """An event as every source adapter must produce it.

    Attributes:
        source (Source): Where it came from.
        source_ref (str): The source's id for it.
        title (str): Its title.
        city (str): Its city.
        start_local_date (date): First day, local.
        end_local_date (date): Last day, local.
        timezone (str): Its IANA timezone.
        category (EventCategory): What kind of event.
        date_precision (DatePrecision): How exact the dates are.
        status (EventStatus): Whether it's on.
        confidence (float): How sure the source is, 0 to 1.
        venue (str | None): Where.
        country (str | None): Its country code.
        latitude (float | None): Where.
        longitude (float | None): Where.
        start_at_utc (datetime | None): When it starts.
        end_at_utc (datetime | None): When it ends.
        expected_attendance (int | None): How many people.
        impact_rank (int | None): The source's impact rank.
        local_rank (int | None): The source's local rank.
        url (str | None): A link.
        source_updated_at (datetime | None): When the source last changed it.
        payload (dict[str, Any]): The raw record.
    """

    source: Source
    source_ref: str
    title: str
    city: str
    start_local_date: date
    end_local_date: date

    timezone: str = "UTC"
    category: EventCategory = EventCategory.UNKNOWN
    date_precision: DatePrecision = DatePrecision.DAY
    status: EventStatus = EventStatus.ACTIVE
    confidence: float = 1.0

    venue: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    start_at_utc: datetime | None = None
    end_at_utc: datetime | None = None
    expected_attendance: int | None = None
    impact_rank: int | None = None
    local_rank: int | None = None
    url: str | None = None

    source_updated_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Checks the record.

        Raises:
            ValueError: A field is missing, empty or out of range.
        """
        if not self.source_ref:
            raise ValueError("source_ref is required")
        if not self.title.strip():
            raise ValueError("title is empty")
        if not self.city.strip():
            raise ValueError("city is empty")
        if not normalize_title(self.title):
            raise ValueError(f"title {self.title!r} normalizes to empty")
        if not slugify_city(self.city):
            raise ValueError(f"city {self.city!r} normalizes to empty")
        if self.end_local_date < self.start_local_date:
            raise ValueError(
                f"end {self.end_local_date} precedes start {self.start_local_date}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} outside 0..1")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be set together")
        if self.latitude is not None and not -90.0 <= self.latitude <= 90.0:
            raise ValueError(
                f"latitude {self.latitude} out of range -- check for swapped lon/lat"
            )
        if self.longitude is not None and not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude {self.longitude} out of range")

    @property
    def title_norm(self) -> str:
        """The normalized title.

        Returns:
            str: The title, normalized.
        """
        return normalize_title(self.title)

    @property
    def dedupe_key(self) -> str:
        """The event's stable identity.

        Returns:
            str: The key.
        """
        return dedupe_key(
            title=self.title, city=self.city, start_local_date=self.start_local_date
        )

    def as_row(self) -> dict[str, Any]:
        """Gives the column values for the canonical `events` row.

        Returns:
            dict[str, Any]: Values by column name.
        """
        return {
            "dedupe_key": self.dedupe_key,
            "title": self.title,
            "title_norm": self.title_norm,
            "category": self.category,
            "venue": self.venue,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_local_date": self.start_local_date,
            "end_local_date": self.end_local_date,
            "start_at_utc": self.start_at_utc,
            "end_at_utc": self.end_at_utc,
            "timezone": self.timezone,
            "date_precision": self.date_precision,
            "expected_attendance": self.expected_attendance,
            "impact_rank": self.impact_rank,
            "local_rank": self.local_rank,
            "confidence": self.confidence,
            "status": self.status,
            "url": self.url,
            "primary_source": self.source,
        }
