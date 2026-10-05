"""Canonical event contract shared by every external source adapter.

PredictHQ keys its records by event, AskNews keys them by article, and both must
land on the same row for the same real-world event -- so the dedupe key and the
field normalizers live here rather than in either adapter.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence


class Source(StrEnum):
    PREDICTHQ = "predicthq"
    ASKNEWS = "asknews"


class EventStatus(StrEnum):
    ACTIVE = "active"
    PROVISIONAL = "provisional"  # extracted from text, not yet corroborated
    CANCELLED = "cancelled"
    DELETED = "deleted"  # withdrawn upstream


class DatePrecision(StrEnum):
    """How precisely the source pinned the date.

    Anything coarser than DAY is unusable for per-night pricing but still worth
    keeping as early signal, so it is recorded rather than rounded away.
    """

    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"


class EventCategory(StrEnum):
    """PredictHQ's taxonomy, adopted project-wide.

    Text sources classify into these buckets instead of inventing a second
    vocabulary.
    """

    ACADEMIC = "academic"
    AIRPORT_DELAYS = "airport-delays"
    COMMUNITY = "community"
    CONCERTS = "concerts"
    CONFERENCES = "conferences"
    DAYLIGHT_SAVINGS = "daylight-savings"
    DISASTERS = "disasters"
    EXPOS = "expos"
    FESTIVALS = "festivals"
    HEALTH_WARNINGS = "health-warnings"
    OBSERVANCES = "observances"
    PERFORMING_ARTS = "performing-arts"
    POLITICS = "politics"
    PUBLIC_HOLIDAYS = "public-holidays"
    SCHOOL_HOLIDAYS = "school-holidays"
    SEVERE_WEATHER = "severe-weather"
    SPORTS = "sports"
    TERROR = "terror"
    UNKNOWN = "unknown"


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
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(title: str) -> str:
    """Reduce a title to the part two sources are likely to agree on."""
    text = _strip_accents(title).lower()
    text = _BRACKETED.sub(" ", text)
    for pattern in (_PRESENTER_TAIL, _GUEST_TAIL, _TOUR_TAIL):
        text = pattern.sub("", text)
    text = _NON_ALNUM.sub(" ", text).strip()
    # "fontaines d.c." and "fontaines dc" must collapse to one key.
    text = _INITIALISM.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = _LEADING_ARTICLE.sub("", text)
    return " ".join(text.split())


def slugify_city(city: str) -> str:
    """Normalize a city name. Drops any trailing region, e.g. "Dublin, Ireland"."""
    head = city.split(",")[0]
    slug = _NON_ALNUM.sub("-", _strip_accents(head).lower())
    return slug.strip("-")


def dedupe_key(*, title: str, city: str, start_local_date: date) -> str:
    """Stable identity for a real-world event occurrence.

    Category is deliberately excluded: two sources routinely disagree on it, and
    disagreement must not split one event into two rows.
    """
    basis = (
        f"{normalize_title(title)}|{slugify_city(city)}|{start_local_date.isoformat()}"
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def resolve_timezone(name: str | None) -> tzinfo:
    """IANA name to tzinfo, falling back to UTC for missing or unknown zones."""
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def to_local_date(moment: datetime, timezone: str | None) -> date:
    """Calendar date in the event's own timezone.

    A stay-night is local, so a 21:00 event must not drift onto the next night
    just because its UTC timestamp crosses midnight.
    """
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(resolve_timezone(timezone)).date()


def coords_from_geojson(
    location: Sequence[float] | None,
) -> tuple[float | None, float | None]:
    """PredictHQ's `location` is GeoJSON order -- [longitude, latitude]."""
    if not location or len(location) < 2:
        return None, None
    longitude, latitude = float(location[0]), float(location[1])
    return latitude, longitude


@dataclass(slots=True)
class NormalizedEvent:
    """What every adapter must produce. Invalid records raise on construction."""

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
        return normalize_title(self.title)

    @property
    def city_slug(self) -> str:
        return slugify_city(self.city)

    @property
    def dedupe_key(self) -> str:
        return dedupe_key(
            title=self.title, city=self.city, start_local_date=self.start_local_date
        )

    def mas_row(self) -> dict[str, Any]:
        """Column values for the canonical `events` row."""
        return {
            "dedupe_key": self.dedupe_key,
            "title": self.title,
            "title_norm": self.title_norm,
            "category": self.category,
            "venue": self.venue,
            "city": self.city,
            "city_slug": self.city_slug,
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
