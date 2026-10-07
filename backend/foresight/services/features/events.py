"""Stored events as the per-night `expected_attendance` feature the models use."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import select

from foresight.database.models.external import Event
from foresight.ingest.normalize import DatePrecision, EventStatus, slugify_city

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

FEATURE = "expected_attendance"

# Withdrawn events must not keep inflating demand.
_EXCLUDED = {EventStatus.DELETED, EventStatus.CANCELLED}
_EARTH_RADIUS_KM = 6371.0


def nightly_attendance(
    events: Iterable[Event],
    start: date,
    end: date,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
) -> pd.Series:
    """Total expected attendance per night, start..end inclusive.

    A multi-day event's attendance is spread evenly over its nights. Provisional
    events count in proportion to their confidence. Events without a day-precise
    date or an attendance estimate contribute nothing.

    With a hotel point and `radius_km`, events whose venue lies farther away are
    dropped; events with no coordinates are kept, since ingest already
    geo-filtered them.
    """
    nights = pd.date_range(start, end, freq="D").date
    totals = dict.fromkeys(nights, 0.0)
    near = latitude is not None and longitude is not None and radius_km is not None

    for event in events:
        if (
            event.status in _EXCLUDED
            or event.date_precision != DatePrecision.DAY
            or not event.expected_attendance
        ):
            continue
        if (
            near
            and event.latitude is not None
            and _distance_km(latitude, longitude, event.latitude, event.longitude)
            > radius_km
        ):
            continue

        span = (event.end_local_date - event.start_local_date).days + 1
        per_night = event.expected_attendance * event.confidence / span
        for offset in range(span):
            night = event.start_local_date + timedelta(days=offset)
            if night in totals:
                totals[night] += per_night

    return pd.Series(
        [round(v) for v in totals.values()],
        index=pd.Index(nights, name="stay_date"),
        name=FEATURE,
        dtype=int,
    )


async def load_events(
    session: AsyncSession, city: str, start: date, end: date
) -> list[Event]:
    """Events in `city` overlapping start..end."""
    result = await session.scalars(
        select(Event).where(
            Event.city_slug == slugify_city(city),
            Event.start_local_date <= end,
            Event.end_local_date >= start,
        )
    )
    return list(result)


async def event_features(
    session: AsyncSession,
    *,
    city: str,
    start: date,
    end: date,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
) -> pd.Series:
    """`nightly_attendance` for a market, read from the events table."""
    events = await load_events(session, city, start, end)
    return nightly_attendance(
        events,
        start,
        end,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = phi2 - phi1, math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))
