"""What a hotel manager says about the rate recommended for a night."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base
from foresight.database.enums import FeedbackReasonTag, FeedbackTiming, FeedbackVerdict


class Feedback(Base):
    """One version of the manager's feedback on one room type and night.

    Rows are only ever added. Changing feedback adds the next `version` for the
    same room type and night; the highest version is the current one and the
    earlier ones are kept, with their times.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.id", ondelete="CASCADE"), index=True
    )
    stay_date: Mapped[date] = mapped_column(Date)  # the night, past or future
    version: Mapped[int]  # increments per room type and night, from 1

    # The recommendation the manager saw. Null for a past night that was never
    # saved. SET NULL: the feedback outlives its snapshot.
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_snapshots.id", ondelete="SET NULL"), index=True
    )
    # Who gave it. Null until sign-in is required on every route; SET NULL so
    # deleting a user keeps what they said.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    verdict: Mapped[FeedbackVerdict] = mapped_column(
        SAEnum(FeedbackVerdict, native_enum=False, length=20)
    )
    # The rate the manager would charge, if they gave one.
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Why, two ways: tags from a fixed list, and free text. Tags are stored as
    # VARCHARs, so a new tag needs no migration.
    reason_tags: Mapped[list[FeedbackReasonTag]] = mapped_column(
        ARRAY(SAEnum(FeedbackReasonTag, native_enum=False, length=40)),
        server_default=text("'{}'"),
    )
    reason_text: Mapped[str | None] = mapped_column(Text)
    timing: Mapped[FeedbackTiming] = mapped_column(
        SAEnum(FeedbackTiming, native_enum=False, length=10)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        # One row per version of a night's feedback, so two simultaneous edits
        # can't both become the same version. Leads on hotel_id, so it also
        # serves as the foreign key index.
        UniqueConstraint("hotel_id", "room_type_id", "stay_date", "version"),
        # Listing a hotel's feedback over a range of nights.
        Index(
            "ix_feedback_hotel_id_stay_date_created_at",
            "hotel_id",
            "stay_date",
            "created_at",
        ),
    )
