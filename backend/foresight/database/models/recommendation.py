"""Every recommended rate we produced, per night"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class RecommendationSnapshot(Base):
    """One recommended rate for one room type and night, as produced at one moment."""

    __tablename__ = "recommendation_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), index=True
    )
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.id", ondelete="CASCADE")
    )
    stay_date: Mapped[date] = mapped_column(Date)
    model_id: Mapped[int] = mapped_column(
        # No cascade: a model with snapshots can't be deleted (history stays).
        ForeignKey("pricing_models.id", ondelete="NO ACTION"),
        index=True,
    )
    model_version: Mapped[str] = mapped_column(String(60))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    interval_low: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    interval_high: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    interval_level: Mapped[float]  # coverage of the interval, e.g. 0.8
    uncertainty: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB)  # baseline + factor list
    # What the model read for this night: its input row, the events on the
    # night and where the weather came from. Returned with the recommendation.
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # SHA-256 of the model id and `inputs`. A request whose hash matches the
    # latest snapshot reuses it instead of running the model (decision 0038).
    inputs_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_recommendation_snapshots_room_type_id_stay_date_created_at",
            "room_type_id",
            "stay_date",
            "created_at",
        ),
    )
