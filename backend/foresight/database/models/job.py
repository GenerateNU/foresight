"""Background jobs: ingests started through the API."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base
from foresight.database.enums import JobKind, JobStatus


class Job(Base):
    """One run of a job for a hotel, and how far it got.

    The runner commits after each chunk of work together with `progress`, so
    the row always describes what is actually saved.
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

    params: Mapped[dict[str, Any]] = mapped_column(JSONB)  # resolved inputs
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    # Where to pick up if the run ends early: the `start` to send again, or the
    # `end` for a run walking backwards. Null once it succeeds.
    resume_from: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
