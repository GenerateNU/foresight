"""AskNews adapter: what survives extraction, what gets dropped, and the client."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from foresight.ingest import asknews
from foresight.ingest.asknews import (
    AskNewsClient,
    CityTarget,
    RejectReason,
    collect_events,
    extract_batch,
    extract_event,
)
from foresight.ingest.normalize import (
    DatePrecision,
    EventCategory,
    EventStatus,
    NormalizedEvent,
    Source,
)

TODAY = date(2026, 6, 1)
DUBLIN = CityTarget(
    name="Dublin",
    timezone="Europe/Dublin",
    country="IE",
    aliases=("Baile Atha Cliath",),
)
LISBON = CityTarget(name="Lisbon", timezone="Europe/Lisbon", country="PT")
CITIES = (DUBLIN, LISBON)


def article(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "article_url": "https://news.example/forbidden-fruit",
        "eng_title": "Forbidden Fruit announces August dates for Dublin",
        "summary": (
            "Organisers confirmed the festival will return to the Royal Hospital "
            "Kilmainham in Dublin on August 28-30, 2026, with tickets on sale Friday."
        ),
        "key_points": ["Tickets go on sale Friday"],
        "pub_date": "2026-05-20T09:30:00+00:00",
        "entities": {"Event": ["Forbidden Fruit"], "Location": ["Dublin", "Ireland"]},
        "country": "IE",
        "page_rank": 3,
        "language": "en",
    }
    return base | overrides


def test_a_clean_announcement_becomes_a_provisional_event() -> None:
    event = extract_event(article(), CITIES, today=TODAY)

    assert isinstance(event, NormalizedEvent)
    assert event.source is Source.ASKNEWS
    assert event.source_ref == "https://news.example/forbidden-fruit"
    assert event.title == "Forbidden Fruit"
    assert event.city == "Dublin"
    assert event.start_local_date == date(2026, 8, 28)
    assert event.end_local_date == date(2026, 8, 30)
    assert event.category is EventCategory.FESTIVALS
    assert event.date_precision is DatePrecision.DAY
    assert event.status is EventStatus.PROVISIONAL


def test_timezone_comes_from_the_city_not_the_article() -> None:
    event = extract_event(article(), CITIES, today=TODAY)

    assert isinstance(event, NormalizedEvent)
    assert event.timezone == "Europe/Dublin"
    assert event.country == "IE"


def test_extraction_is_never_fully_confident() -> None:
    event = extract_event(article(), CITIES, today=TODAY)

    assert isinstance(event, NormalizedEvent)
    assert 0.0 < event.confidence <= 0.95


def test_an_event_entity_names_the_event_rather_than_the_headline() -> None:
    headline_only = article(entities={"Location": ["Dublin"]})

    titled = extract_event(article(), CITIES, today=TODAY)
    untitled = extract_event(headline_only, CITIES, today=TODAY)

    assert isinstance(titled, NormalizedEvent)
    assert isinstance(untitled, NormalizedEvent)
    assert titled.title == "Forbidden Fruit"
    assert untitled.title.startswith("Forbidden Fruit announces")
    # The entity hit is the stronger signal, so it must score higher.
    assert titled.confidence > untitled.confidence


def test_a_location_entity_outscores_a_bare_mention_in_the_body() -> None:
    weak = article(entities={"Event": ["Forbidden Fruit"]})

    strong_event = extract_event(article(), CITIES, today=TODAY)
    weak_event = extract_event(weak, CITIES, today=TODAY)

    assert isinstance(strong_event, NormalizedEvent)
    assert isinstance(weak_event, NormalizedEvent)
    assert strong_event.confidence > weak_event.confidence


def test_an_alias_resolves_to_the_same_city() -> None:
    aliased = article(
        entities={"Event": ["Forbidden Fruit"], "Location": ["Baile Atha Cliath"]},
        summary="Returns on August 28-30, 2026.",
        eng_title="Festival returns",
    )

    event = extract_event(aliased, CITIES, today=TODAY)

    assert isinstance(event, NormalizedEvent)
    assert event.city_slug == "dublin"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {
                "eng_title": "Glastonbury announces dates",
                "summary": "The festival runs August 28-30, 2026 in Somerset.",
                "entities": {"Event": ["Glastonbury"], "Location": ["Somerset"]},
            },
            RejectReason.NO_CITY_MATCH,
        ),
        (
            {
                "summary": "A Dublin festival will return, dates to be confirmed.",
                "eng_title": "Dublin festival to return",
                "entities": {"Location": ["Dublin"]},
            },
            RejectReason.NO_RESOLVABLE_DATE,
        ),
        (
            {
                "summary": "The Dublin festival was held on August 28, 2025.",
                "eng_title": "Dublin festival review",
                "key_points": [],
                "entities": {"Location": ["Dublin"]},
            },
            RejectReason.RETROSPECTIVE,
        ),
        (
            {
                "summary": "The Dublin festival is scheduled for August 28, 2035.",
                "eng_title": "Dublin festival long-range plan",
                "entities": {"Location": ["Dublin"]},
            },
            RejectReason.BEYOND_HORIZON,
        ),
        ({"article_url": ""}, RejectReason.MALFORMED_RECORD),
        (
            {"eng_title": "", "title": "", "summary": "", "key_points": []},
            RejectReason.MALFORMED_RECORD,
        ),
    ],
)
def test_unusable_articles_are_rejected_with_a_reason(
    overrides: dict[str, Any], reason: RejectReason
) -> None:
    assert extract_event(article(**overrides), CITIES, today=TODAY) is reason


def test_an_event_that_already_finished_is_rejected_as_past() -> None:
    stale = article(
        pub_date="2026-01-10T09:00:00+00:00",
        eng_title="Dublin parade set for March 17",
        summary="The Dublin parade is scheduled for March 17, 2026.",
        entities={"Location": ["Dublin"]},
    )

    assert extract_event(stale, CITIES, today=TODAY) is RejectReason.EVENT_ALREADY_PAST


def test_an_event_running_across_today_is_still_kept() -> None:
    ongoing = article(
        pub_date="2026-05-25T09:00:00+00:00",
        eng_title="Dublin festival under way",
        summary="The Dublin festival is scheduled for May 30 - June 3, 2026.",
        entities={"Location": ["Dublin"]},
    )

    event = extract_event(ongoing, CITIES, today=TODAY)

    assert isinstance(event, NormalizedEvent)
    assert event.start_local_date < TODAY <= event.end_local_date


def test_the_same_event_from_two_outlets_collapses_to_one_row() -> None:
    wire_copy = article(
        article_url="https://other.example/ff",
        eng_title="Dublin festival confirms summer return",
        entities={"Event": ["Forbidden Fruit"], "Location": ["Dublin"]},
    )

    events, report = extract_batch([article(), wire_copy], CITIES, today=TODAY)

    assert len(events) == 1
    assert report.articles_seen == 2
    assert report.events_kept == 1
    assert report.rejected[RejectReason.DUPLICATE_IN_BATCH.value] == 1


def test_the_higher_confidence_sighting_wins_a_collapse() -> None:
    weak = article(
        article_url="https://other.example/ff",
        entities={"Event": ["Forbidden Fruit"]},
    )

    events, _ = extract_batch([weak, article()], CITIES, today=TODAY)

    assert len(events) == 1
    assert events[0].source_ref == "https://news.example/forbidden-fruit"


def test_two_outlets_do_not_collapse_without_an_event_entity() -> None:
    """A known limit: headlines differ, so the dedupe key differs.

    AskNews supplies an Event entity for most announcements. Where it does
    not, the same event arrives twice and only PredictHQ corroboration or a
    later title match will merge it.
    """
    wire_copy = article(
        article_url="https://other.example/ff",
        eng_title="Forbidden Fruit returns to Dublin",
        entities={"Location": ["Dublin"]},
    )

    events, _ = extract_batch([article(), wire_copy], CITIES, today=TODAY)

    assert len(events) == 2


def test_the_report_tallies_everything_that_came_in() -> None:
    batch = [
        article(),
        article(
            article_url="https://x.example/1", summary="No date here.", key_points=[]
        ),
        article(
            article_url="https://x.example/2",
            entities={"Location": ["Somerset"]},
            eng_title="Somerset show",
            summary="Runs August 28-30, 2026 in Somerset.",
        ),
    ]

    events, report = extract_batch(batch, CITIES, today=TODAY)

    assert report.articles_seen == 3
    assert report.events_kept == len(events) == 1
    assert report.articles_rejected == 2
    assert report.by_city["dublin"] == 1
    assert report.by_precision["day"] == 1
    assert "articles seen" in report.render()


def test_events_are_returned_in_date_order() -> None:
    later = article(
        article_url="https://x.example/later",
        eng_title="Lisbon summit",
        summary="The Lisbon summit is scheduled for October 5, 2026.",
        entities={"Event": ["Lisbon Summit"], "Location": ["Lisbon"]},
    )

    events, _ = extract_batch([later, article()], CITIES, today=TODAY)

    assert [e.start_local_date for e in events] == sorted(
        e.start_local_date for e in events
    )


# --- client ---------------------------------------------------------------


def build_client(handler: Any) -> tuple[AskNewsClient, dict[str, int]]:
    calls: dict[str, int] = {"token": 0, "search": 0}

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            calls["token"] += 1
        else:
            calls["search"] += 1
        return handler(request, calls)

    http = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return AskNewsClient("id", "secret", http=http), calls


def ok(request: httpx.Request, _calls: dict[str, int]) -> httpx.Response:
    if request.url.path.endswith("/token"):
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    return httpx.Response(200, json={"as_dicts": [article()], "offset": 0})


async def test_search_authenticates_then_returns_articles() -> None:
    client, calls = build_client(ok)

    articles = await client.search_news(query="festival", n_articles=5)

    assert calls == {"token": 1, "search": 1}
    assert articles[0]["article_url"] == "https://news.example/forbidden-fruit"


async def test_the_token_is_reused_across_searches() -> None:
    client, calls = build_client(ok)

    await client.search_news(query="a")
    await client.search_news(query="b")

    assert calls["token"] == 1
    assert calls["search"] == 2


async def test_the_bearer_token_is_sent_on_the_search() -> None:
    seen: list[str] = []

    def capture(request: httpx.Request, _calls: dict[str, int]) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"as_dicts": []})

    client, _ = build_client(capture)
    await client.search_news(query="a")

    assert seen == ["Bearer tok"]


async def test_a_rate_limited_search_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asknews.asyncio, "sleep", no_sleep)

    def throttle(request: httpx.Request, calls: dict[str, int]) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if calls["search"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={})
        return httpx.Response(200, json={"as_dicts": [article()]})

    client, calls = build_client(throttle)
    articles = await client.search_news(query="festival")

    assert calls["search"] == 2
    assert len(articles) == 1


async def test_a_persistent_server_error_is_raised() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    def broken(request: httpx.Request, _calls: dict[str, int]) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(503, json={})

    client, _ = build_client(broken)
    asknews.asyncio.sleep = no_sleep  # type: ignore[assignment]

    with pytest.raises(httpx.HTTPStatusError):
        await client.search_news(query="festival")


async def test_a_token_response_without_a_token_fails_loudly() -> None:
    def tokenless(request: httpx.Request, _calls: dict[str, int]) -> httpx.Response:
        return httpx.Response(200, json={"detail": "nope"})

    client, _ = build_client(tokenless)

    with pytest.raises(ValueError, match="access_token"):
        await client.search_news(query="festival")


async def test_collect_events_is_one_call_a_scheduled_worker_can_make() -> None:
    """The cron path end to end: fetch every query, extract one clean batch."""
    queries_seen: list[str] = []
    hours_seen: list[str] = []

    def handler(request: httpx.Request, _calls: dict[str, int]) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        queries_seen.append(request.url.params.get("query", ""))
        hours_seen.append(request.url.params.get("hours_back", ""))
        return httpx.Response(200, json={"as_dicts": [article()]})

    client, calls = build_client(handler)
    events, report = await collect_events(
        client, CITIES, today=TODAY, queries=("a", "b"), hours_back=6
    )

    assert calls["search"] == 2
    assert queries_seen == ["a", "b"]
    assert hours_seen == ["6", "6"]
    assert report.queries_run == 2
    assert report.articles_seen == 2
    # The same article from both queries is one event, not two.
    assert len(events) == 1
    assert report.rejected[RejectReason.DUPLICATE_IN_BATCH.value] == 1
