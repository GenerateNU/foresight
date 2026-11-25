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

    Identified by `dedupe_key` (normalized title, city and local start date),
    so the same festival listed twice lands on one row.

    Attributes:
        id (int): Primary key.
        dedupe_key (str): The event's identity across sources.
        title (str): As the winning source gave it.
        title_norm (str): The normalized title.
        category (EventCategory): Its category.
        venue (str | None): Where it is.
        city_id (int): Its market.
        country (str | None): ISO-3166 alpha-2 code.
        latitude (float | None): Where it is.
        longitude (float | None): Where it is.
        start_local_date (date): First night, local to the city.
        end_local_date (date): Last night, inclusive, local to the city.
        start_at_utc (datetime | None): When it starts, if the source said.
        end_at_utc (datetime | None): When it ends, if the source said.
        timezone (str): The event's IANA timezone.
        date_precision (DatePrecision): How precisely the date is known.
        expected_attendance (int | None): People expected.
        impact_rank (int | None): PredictHQ's rank, 0-100.
        local_rank (int | None): PredictHQ's local rank, 0-100.
        confidence (float): How sure the source is, 0-1.
        status (EventStatus): Whether it's still on.
        url (str | None): A link to it.
        primary_source (Source): The source whose values the row holds.
        first_seen_at (datetime): When we first saw it.
        last_seen_at (datetime): When we last saw it.
        observations (list[EventObservation]): Each source's sightings.
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
    country: Mapped[str | None] = mapped_column(String(2))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
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
    impact_rank: Mapped[int | None]
    local_rank: Mapped[int | None]
    confidence: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus, native_enum=False, length=20),
        default=EventStatus.ACTIVE,
    )
    url: Mapped[str | None] = mapped_column(String(600))
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

    __table_args__ = (Index(None, "city_id", "start_local_date"),)


class EventObservation(Base):
    """One source's raw sighting of an event, kept as it came.

    Keyed on the source and its own id, so re-runs change nothing and a revised
    record is recognised rather than duplicated.

    Attributes:
        id (int): Primary key.
        event_id (int | None): The merged event; null when the sighting can't
            be resolved to a dated event, or the event was deleted.
        source (Source): Where it came from.
        source_ref (str): The source's own id for it.
        source_updated_at (datetime | None): When the source last changed it.
        status (EventStatus | None): What this sighting reported.
        payload (dict[str, Any]): The source's record, as it came.
        captured_at (datetime): When we saw it.
        event (Event | None): The merged event.
    """

    __tablename__ = "event_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[Source] = mapped_column(SAEnum(Source, native_enum=False, length=40))
    source_ref: Mapped[str] = mapped_column(String(600))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
