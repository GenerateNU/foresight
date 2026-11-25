from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base
from foresight.database.enums import JobKind, JobStatus


class Job(Base):
    """One run of a background job for a hotel, and how far it got.

    The worker commits `progress` with each chunk of work, so the row always
    describes what is saved.

    Attributes:
        id (int): Primary key.
        hotel_id (int): The hotel.
        kind (JobKind): What it does.
        status (JobStatus): Where it is in its life.
        params (dict[str, Any]): Its inputs, as resolved when queued.
        progress (dict[str, Any]): Counts so far.
        error (str | None): Why it stopped or failed.
        resume_from (date | None): Where to pick up if a backfill ended early:
            the `end` to send again. Null once it succeeds.
        created_at (datetime): When it was queued.
        started_at (datetime | None): When it started running.
        finished_at (datetime | None): When it ended.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[JobKind] = mapped_column(SAEnum(JobKind, native_enum=False, length=40))
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=20), default=JobStatus.QUEUED
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    resume_from: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
