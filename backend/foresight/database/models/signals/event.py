"""Real-world events, merged across sources, and each source's raw sightings."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from foresight.database.base import Base
from foresight.database.enums import DatePrecision, EventCategory, EventStatus, Source


class Event(Base):
    """One real-world event occurrence, merged across sources.

    Identified by `dedupe_key` (normalized title + city + local start date) so
    the same festival seen by PredictHQ and by AskNews lands on one row.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)

    title: Mapped[str] = mapped_column(String(300))
    title_norm: Mapped[str] = mapped_column(String(300), index=True)
    category: Mapped[EventCategory] = mapped_column(
        SAEnum(EventCategory, native_enum=False, length=40),
        default=EventCategory.UNKNOWN,
    )

    venue: Mapped[str | None] = mapped_column(String(200))
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO-3166 alpha-2
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    # Local dates, not UTC: a stay-night is local to the hotel. Inclusive range.
    start_local_date: Mapped[date] = mapped_column(Date)
    end_local_date: Mapped[date] = mapped_column(Date)
    start_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    date_precision: Mapped[DatePrecision] = mapped_column(
        SAEnum(DatePrecision, native_enum=False, length=20),
        default=DatePrecision.DAY,
    )

    expected_attendance: Mapped[int | None]
    impact_rank: Mapped[int | None]  # PredictHQ rank, 0-100
    local_rank: Mapped[int | None]  # PredictHQ local_rank, 0-100
    confidence: Mapped[float] = mapped_column(default=1.0)

    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus, native_enum=False, length=20),
        default=EventStatus.ACTIVE,
    )
    url: Mapped[str | None] = mapped_column(String(600))

    # Which source currently owns these values, by precedence.
    primary_source: Mapped[Source] = mapped_column(
        SAEnum(Source, native_enum=False, length=40)
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    observations: Mapped[list["EventObservation"]] = relationship(
        back_populates="event", lazy="raise", passive_deletes=True
    )

    # Serves the core lookup: what is happening near this hotel on this night.
    __table_args__ = (Index(None, "city_id", "start_local_date"),)


class EventObservation(Base):
    """One source's raw sighting of an event, kept verbatim.

    Append-only and keyed on (source, source_ref) -- the PredictHQ event id or
    the AskNews article URL. This is what makes re-runs idempotent and lets a
    revised upstream record be recognised rather than duplicated.

    `event_id` is null when a sighting cannot be resolved to a dated event, e.g.
    an article that announces a festival without saying when it is.
    """

    __tablename__ = "event_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )

    source: Mapped[Source] = mapped_column(SAEnum(Source, native_enum=False, length=40))
    source_ref: Mapped[str] = mapped_column(String(600))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What this sighting reported; null only for rows predating the column.
    status: Mapped[EventStatus | None] = mapped_column(
        SAEnum(EventStatus, native_enum=False, length=20)
    )

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    event: Mapped["Event | None"] = relationship(
        back_populates="observations", lazy="raise"
    )

    __table_args__ = (UniqueConstraint("source", "source_ref"),)
