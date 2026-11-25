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
from foresight.database.enums import FeedbackReasonTag


class Feedback(Base):
    """One version of the manager's feedback on one room type and night.

    Rows are only ever added. A change is the next `version` for the same
    room type and night; the highest is the current one, and earlier ones
    keep their times. The unique version per night stops two simultaneous
    edits becoming the same version.

    Attributes:
        id (int): Primary key.
        hotel_id (int): The hotel.
        room_type_id (int): The room type.
        stay_date (date): The night, past or future.
        version (int): 1 for the first feedback on the night, then one more
            per change.
        snapshot_id (int | None): The recommendation the manager saw; null if
            it was deleted, or for a past night never saved.
        user_id (int | None): Who gave it; null for feedback saved before
            sign-in was required, or a deleted user.
        rate (Decimal | None): The rate the manager chose, before VAT.
        reason_tags (list[FeedbackReasonTag]): Why, from a fixed list.
        reason_text (str | None): Why, in the manager's words.
        created_at (datetime): When this version was given.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.id", ondelete="CASCADE"), index=True
    )
    stay_date: Mapped[date] = mapped_column(Date)
    version: Mapped[int]
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_snapshots.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    reason_tags: Mapped[list[FeedbackReasonTag]] = mapped_column(
        ARRAY(SAEnum(FeedbackReasonTag, native_enum=False, length=40)),
        server_default=text("'{}'"),
    )
    reason_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        UniqueConstraint("hotel_id", "room_type_id", "stay_date", "version"),
        Index(
            "ix_feedback_hotel_id_stay_date_created_at",
            "hotel_id",
            "stay_date",
            "created_at",
        ),
    )
