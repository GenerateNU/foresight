"""AskNews adapter: news articles in, provisional events out.

AskNews indexes articles, not events, so every record here is an inference:
an article *mentions* a festival, and we decide whether it pins down a title,
a city we operate in, and a date precise enough to price a night against.
Most articles do not, and dropping those is the bulk of the work -- the
rejection tally on `IngestReport` is the audit trail for what got dropped and
why.

Everything produced is `EventStatus.PROVISIONAL`. PredictHQ owns a record once
it corroborates one; this source exists to see an event before PredictHQ does.

One event per article: `event_observations` is unique on (source, source_ref)
and source_ref is the article URL, so a single article cannot carry two
sightings. Where an article announces several events we keep the first that
resolves cleanly.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from foresight.ingest.normalize import (
    DatePrecision,
    EventCategory,
    EventStatus,
    NormalizedEvent,
    Source,
    normalize_title,
    slugify_city,
)
from foresight.ingest.textdates import (
    MAX_LOOKAHEAD_DAYS,
    looks_retrospective,
    resolve_date,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import httpx

DEFAULT_API_BASE_URL = "https://api.asknews.app"
DEFAULT_TOKEN_URL = "https://auth.asknews.app/oauth2/token"
SEARCH_PATH = "/v1/news/search"

# Event-shaped phrasing, paired with a city at query time. Searching these
# terms globally returns mostly events in cities we do not sell rooms in: an
# unscoped run rejected 188 of 198 articles on city alone.
EVENT_TERMS = (
    "festival concert conference expo parade marathon "
    "announces dates lineup tickets venue"
)

_MAX_ATTEMPTS = 3
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_TOKEN_EXPIRY_SLACK_SECONDS = 60

_CATEGORY_KEYWORDS: tuple[tuple[EventCategory, tuple[str, ...]], ...] = (
    (EventCategory.FESTIVALS, ("festival", "fest", "carnival", "mardi gras")),
    (EventCategory.CONCERTS, ("concert", "gig", "tour date", "live at", "headline")),
    (
        EventCategory.SPORTS,
        ("match", "fixture", "tournament", "marathon", "championship", "cup final"),
    ),
    (
        EventCategory.CONFERENCES,
        ("conference", "summit", "symposium", "convention", "congress"),
    ),
    (EventCategory.EXPOS, ("expo", "trade show", "fair", "exhibition")),
    (
        EventCategory.PERFORMING_ARTS,
        ("theatre", "theater", "opera", "ballet", "musical", "play opens"),
    ),
    (EventCategory.COMMUNITY, ("parade", "street party", "community", "pride")),
    (EventCategory.ACADEMIC, ("graduation", "commencement", "semester", "freshers")),
    (EventCategory.POLITICS, ("election", "referendum", "state visit", "protest")),
)

_PUBLISHER_TAIL = re.compile(r"\s*[|–—-]\s*[^|–—-]{1,40}$")
_NEWS_PREFIX = re.compile(
    r"^\s*(?:breaking|exclusive|update|watch|live|just in)\s*[:–-]\s*", re.I
)


class RejectReason(StrEnum):
    """Why an article produced no event. The cleaning report is a tally of these."""

    RETROSPECTIVE = "retrospective"
    NO_RESOLVABLE_DATE = "no_resolvable_date"
    EVENT_ALREADY_PAST = "event_already_past"
    BEYOND_HORIZON = "beyond_horizon"
    NO_CITY_MATCH = "no_city_match"
    UNUSABLE_TITLE = "unusable_title"
    DUPLICATE_IN_BATCH = "duplicate_in_batch"
    MALFORMED_RECORD = "malformed_record"


@dataclass(frozen=True, slots=True)
class CityTarget:
    """A city we sell rooms in, and the only places we care about events.

    The timezone comes from here rather than from the article: a stay-night is
    local to the hotel, and an article never states the venue's zone.
    """

    name: str
    timezone: str
    country: str | None = None
    aliases: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        return slugify_city(self.name)

    @property
    def search_terms(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """One search call: what to ask for, and where to allow it from."""

    query: str
    countries: tuple[str, ...] = ()


def plan_searches(
    cities: Sequence[CityTarget], queries: Sequence[str] | None = None
) -> tuple[SearchPlan, ...]:
    """One scoped search per city, unless explicit queries are supplied.

    Scoping at the query is what makes the spend worthwhile -- AskNews bills
    per search, so a global query that we then discard on city is paid-for
    noise.
    """
    if queries is not None:
        return tuple(SearchPlan(query) for query in queries)
    return tuple(
        SearchPlan(
            f"{city.name} {EVENT_TERMS}",
            (city.country,) if city.country else (),
        )
        for city in cities
    )


@dataclass(slots=True)
class IngestReport:
    """What one run saw, kept, and threw away."""

    articles_seen: int = 0
    events_kept: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    by_city: Counter[str] = field(default_factory=Counter)
    by_precision: Counter[str] = field(default_factory=Counter)
    queries_run: int = 0

    @property
    def articles_rejected(self) -> int:
        return sum(self.rejected.values())

    @property
    def keep_rate(self) -> float:
        return self.events_kept / self.articles_seen if self.articles_seen else 0.0

    def render(self) -> str:
        lines = [
            f"queries run        {self.queries_run}",
            f"articles seen      {self.articles_seen}",
            f"events kept        {self.events_kept}  ({self.keep_rate:.0%})",
            f"articles rejected  {self.articles_rejected}",
        ]
        for reason, count in self.rejected.most_common():
            lines.append(f"    {reason:<22} {count}")
        if self.by_city:
            lines.append("events by city")
            for city, count in self.by_city.most_common():
                lines.append(f"    {city:<22} {count}")
        if self.by_precision:
            lines.append("events by date precision")
            for precision, count in self.by_precision.most_common():
                lines.append(f"    {precision:<22} {count}")
        return "\n".join(lines)


class AskNewsClient:
    """Thin async client over the AskNews REST API.

    The SDK would do this too, but it drags in its own HTTP stack and DTO
    layer; the two calls we need are cheaper to own than to depend on.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.AsyncClient,
        base_url: str = DEFAULT_API_BASE_URL,
        token_url: str = DEFAULT_TOKEN_URL,
        scopes: Sequence[str] = ("news",),
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._scopes = tuple(scopes)
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a request, backing off once per retryable status."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = await self._http.request(method, url, **kwargs)
            if response.status_code not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0
            await asyncio.sleep(delay * attempt)
        raise AssertionError("unreachable")

    async def _access_token(self) -> str:
        now = datetime.now(UTC)
        if self._token and self._token_expires_at and now < self._token_expires_at:
            return self._token

        response = await self._request(
            "POST",
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "scope": " ".join(self._scopes),
            },
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ValueError("AskNews token response carried no access_token")
        expires_in = int(payload.get("expires_in", 3600)) - _TOKEN_EXPIRY_SLACK_SECONDS
        self._token = token
        self._token_expires_at = now + timedelta(seconds=max(expires_in, 0))
        return token

    async def search_news(self, **params: Any) -> list[dict[str, Any]]:
        """One page of articles as plain dicts."""
        token = await self._access_token()
        response = await self._request(
            "GET",
            f"{self._base_url}{SEARCH_PATH}",
            params={"return_type": "dicts", **params},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        return list(body.get("as_dicts") or [])


def _clean_title(raw: str) -> str:
    return _PUBLISHER_TAIL.sub("", _NEWS_PREFIX.sub("", raw)).strip()


def _entity_list(article: dict[str, Any], key: str) -> list[str]:
    entities = article.get("entities") or {}
    if not isinstance(entities, dict):
        return []
    values = entities.get(key) or []
    return [str(v) for v in values if str(v).strip()]


def _pick_title(article: dict[str, Any]) -> str:
    """An Event entity names the event; a headline is about the event."""
    for candidate in _entity_list(article, "Event"):
        cleaned = _clean_title(candidate)
        if normalize_title(cleaned):
            return cleaned
    return _clean_title(str(article.get("eng_title") or article.get("title") or ""))


def _match_city(
    article: dict[str, Any], text: str, cities: Sequence[CityTarget]
) -> tuple[CityTarget, bool] | None:
    """Resolve to one of our cities. The flag marks a Location-entity hit."""
    location_slugs = {slugify_city(loc) for loc in _entity_list(article, "Location")}
    haystack = text.lower()
    weak: CityTarget | None = None
    for city in cities:
        for term in city.search_terms:
            if slugify_city(term) in location_slugs:
                return city, True
            if weak is None and re.search(rf"\b{re.escape(term.lower())}\b", haystack):
                weak = city
    return (weak, False) if weak else None


def _classify(text: str) -> EventCategory:
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return EventCategory.UNKNOWN


def _score(
    *,
    precision: DatePrecision,
    explicit_year: bool,
    titled_by_entity: bool,
    strong_city: bool,
) -> float:
    """Never 1.0: an extraction is a guess until another source agrees."""
    confidence = 0.35
    if precision is DatePrecision.DAY:
        confidence += 0.20
    elif precision is DatePrecision.MONTH:
        confidence += 0.05
    if explicit_year:
        confidence += 0.10
    if titled_by_entity:
        confidence += 0.15
    if strong_city:
        confidence += 0.15
    return min(confidence, 0.95)


def _published_on(article: dict[str, Any]) -> datetime | None:
    raw = article.get("pub_date") or article.get("crawl_date")
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def extract_event(
    article: dict[str, Any],
    cities: Sequence[CityTarget],
    *,
    today: date,
    horizon_days: int = MAX_LOOKAHEAD_DAYS,
) -> NormalizedEvent | RejectReason:
    """One article to one event, or the reason it did not make it."""
    url = str(article.get("article_url") or "").strip()
    if not url:
        return RejectReason.MALFORMED_RECORD

    summary = str(article.get("summary") or "")
    headline = str(article.get("eng_title") or article.get("title") or "")
    key_points = " ".join(str(p) for p in (article.get("key_points") or []))
    text = " ".join(filter(None, (headline, summary, key_points)))
    if not text.strip():
        return RejectReason.MALFORMED_RECORD

    if looks_retrospective(text):
        return RejectReason.RETROSPECTIVE

    matched = _match_city(article, text, cities)
    if matched is None:
        return RejectReason.NO_CITY_MATCH
    city, strong_city = matched

    published = _published_on(article)
    reference = min(published.date(), today) if published else today
    resolved = resolve_date(text, reference)
    if resolved is None:
        return RejectReason.NO_RESOLVABLE_DATE
    # An event running across today still prices tonight, so test the end.
    if resolved.end < today:
        return RejectReason.EVENT_ALREADY_PAST
    if (resolved.start - today).days > horizon_days:
        return RejectReason.BEYOND_HORIZON

    entity_titles = _entity_list(article, "Event")
    title = _pick_title(article)
    if not title or not normalize_title(title):
        return RejectReason.UNUSABLE_TITLE

    try:
        return NormalizedEvent(
            source=Source.ASKNEWS,
            source_ref=url,
            title=title,
            city=city.name,
            start_local_date=resolved.start,
            end_local_date=resolved.end,
            timezone=city.timezone,
            category=_classify(text),
            date_precision=resolved.precision,
            status=EventStatus.PROVISIONAL,
            confidence=_score(
                precision=resolved.precision,
                explicit_year=resolved.had_explicit_year,
                titled_by_entity=bool(entity_titles),
                strong_city=strong_city,
            ),
            country=city.country,
            url=url,
            source_updated_at=published,
            payload=article,
        )
    except ValueError:
        return RejectReason.MALFORMED_RECORD


def extract_batch(
    articles: Iterable[dict[str, Any]],
    cities: Sequence[CityTarget],
    *,
    today: date,
    horizon_days: int = MAX_LOOKAHEAD_DAYS,
    report: IngestReport | None = None,
) -> tuple[list[NormalizedEvent], IngestReport]:
    """Extract, then collapse same-event sightings down to the best one.

    Several outlets cover the same announcement, so within-batch collapsing is
    the common case, not an edge case. Highest confidence wins.
    """
    report = report or IngestReport()
    best: dict[str, NormalizedEvent] = {}

    for article in articles:
        report.articles_seen += 1
        outcome = extract_event(article, cities, today=today, horizon_days=horizon_days)
        if isinstance(outcome, RejectReason):
            report.rejected[outcome.value] += 1
            continue

        incumbent = best.get(outcome.dedupe_key)
        if incumbent is None:
            best[outcome.dedupe_key] = outcome
            continue
        report.rejected[RejectReason.DUPLICATE_IN_BATCH.value] += 1
        if outcome.confidence > incumbent.confidence:
            best[outcome.dedupe_key] = outcome

    events = sorted(best.values(), key=lambda e: (e.start_local_date, e.title))
    report.events_kept = len(events)
    for event in events:
        report.by_city[event.city_slug] += 1
        report.by_precision[str(event.date_precision)] += 1
    return events, report


async def collect_events(
    client: AskNewsClient,
    cities: Sequence[CityTarget],
    *,
    today: date,
    queries: Sequence[str] | None = None,
    articles_per_query: int = 50,
    hours_back: int = 24,
    horizon_days: int = MAX_LOOKAHEAD_DAYS,
) -> tuple[list[NormalizedEvent], IngestReport]:
    """Run one scoped search per city and extract a single clean batch.

    This is the whole call a scheduled worker makes. `hours_back` is the
    scheduling knob: an hourly job overlaps with 24, a catch-up run after an
    outage uses more. Pass `queries` to override the per-city plan.
    """
    report = IngestReport()
    collected: list[dict[str, Any]] = []
    for plan in plan_searches(cities, queries):
        report.queries_run += 1
        params: dict[str, Any] = {
            "query": plan.query,
            "n_articles": articles_per_query,
            "hours_back": hours_back,
            "method": "both",
            "strategy": "latest news",
        }
        if plan.countries:
            params["countries"] = list(plan.countries)
        collected.extend(await client.search_news(**params))
    return extract_batch(
        collected, cities, today=today, horizon_days=horizon_days, report=report
    )
