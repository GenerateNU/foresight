"""Normalization contract: identity, idempotency, and the known source gotchas."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from foresight.ingest.normalize import (
    DatePrecision,
    EventCategory,
    NormalizedEvent,
    Source,
    coords_from_geojson,
    dedupe_key,
    normalize_title,
    slugify_city,
    to_local_date,
)


def test_dedupe_key_is_stable_across_runs() -> None:
    args = {
        "title": "Electric Picnic",
        "city": "Stradbally",
        "start_local_date": date(2026, 8, 28),
    }

    assert dedupe_key(**args) == dedupe_key(**args)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Fontaines D.C.", "Fontaines DC"),
        ("The National", "National"),
        ("Hozier - Presented by Aiken Promotions", "Hozier"),
        ("Kneecap feat. special guests", "Kneecap"),
        ("Dua Lipa (Rescheduled)", "Dua Lipa"),
        ("Sigur Rós", "Sigur Ros"),
    ],
)
def test_titles_that_mean_the_same_event_collapse(left: str, right: str) -> None:
    assert normalize_title(left) == normalize_title(right)


def test_distinct_titles_do_not_collapse() -> None:
    assert normalize_title("Longitude Festival") != normalize_title("Latitude Festival")


def test_city_slug_drops_trailing_region() -> None:
    assert slugify_city("Dublin, Ireland") == slugify_city("Dublin") == "dublin"


def test_geojson_coords_are_lon_lat_ordered() -> None:
    # PredictHQ's Dublin: [-6.26, 53.35]. Latitude must come back as 53.35.
    assert coords_from_geojson([-6.26, 53.35]) == (53.35, -6.26)


def test_geojson_coords_tolerate_missing_location() -> None:
    assert coords_from_geojson(None) == (None, None)


def test_local_date_uses_event_timezone_not_utc() -> None:
    # 20:00 on 14 March in Los Angeles is already 15 March in UTC.
    moment = datetime(2026, 3, 15, 3, 0, tzinfo=UTC)

    assert to_local_date(moment, "America/Los_Angeles") == date(2026, 3, 14)
    assert to_local_date(moment, None) == date(2026, 3, 15)


def test_unknown_timezone_falls_back_to_utc() -> None:
    moment = datetime(2026, 3, 15, 3, 0, tzinfo=UTC)

    assert to_local_date(moment, "Mars/Olympus_Mons") == date(2026, 3, 15)


def _event(**overrides: object) -> NormalizedEvent:
    base: dict[str, object] = {
        "source": Source.PREDICTHQ,
        "source_ref": "z13B8ehGzCCZjPM3Ff",
        "title": "Electric Picnic 2026",
        "city": "Stradbally",
        "start_local_date": date(2026, 8, 28),
        "end_local_date": date(2026, 8, 30),
    }
    return NormalizedEvent(**(base | overrides))  # type: ignore[arg-type]


def test_two_sources_seeing_one_event_share_a_dedupe_key() -> None:
    from_phq = _event(title="Electric Picnic 2026", category=EventCategory.FESTIVALS)
    from_news = _event(
        source=Source.ASKNEWS,
        source_ref="https://example.test/electric-picnic",
        title="Electric Picnic 2026 (Festival)",
        city="Stradbally, Ireland",
        category=EventCategory.CONCERTS,
        confidence=0.6,
    )

    assert from_phq.dedupe_key == from_news.dedupe_key


def test_as_row_carries_derived_identity_columns() -> None:
    row = _event().as_row()

    assert row["dedupe_key"] == _event().dedupe_key
    assert row["city_slug"] == "stradbally"
    assert row["primary_source"] is Source.PREDICTHQ
    assert row["date_precision"] is DatePrecision.DAY


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"end_local_date": date(2026, 8, 27)}, "precedes start"),
        ({"confidence": 1.4}, "outside 0..1"),
        ({"latitude": 53.35}, "set together"),
        # Singapore with lon/lat transposed: 103.5 is not a latitude.
        ({"latitude": 103.85, "longitude": 1.29}, "swapped"),
        ({"title": "(Live)"}, "normalizes to empty"),
        ({"source_ref": ""}, "source_ref is required"),
    ],
)
def test_malformed_records_are_rejected(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _event(**overrides)


def test_swapped_coordinates_are_caught_only_when_out_of_range() -> None:
    # A real swap inside both valid ranges cannot be detected here; the
    # coords_from_geojson helper is the defence, not validation.
    assert _event(latitude=53.35, longitude=-6.26).latitude == 53.35


def test_zoneinfo_dependency_is_available() -> None:
    assert ZoneInfo("Europe/Dublin").key == "Europe/Dublin"
