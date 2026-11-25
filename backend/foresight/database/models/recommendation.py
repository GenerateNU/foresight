from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class RecommendationSnapshot(Base):
    """One rate recommended for one room type and night, as shown at one moment.

    Rows are only ever added. A model with snapshots can't be deleted, so the
    record of what was shown stays.

    Attributes:
        id (int): Primary key.
        hotel_id (int): The hotel.
        room_type_id (int): The room type.
        stay_date (date): The night.
        model_id (int): The version that priced it.
        rate (Decimal): The rate shown, before VAT.
        factors (dict[str, Any]): The explanation: summary, baseline and
            factors.
        inputs (dict[str, Any]): What the model read: its input row, the
            events on the night and whether event data covered it.
        created_at (datetime): When it was shown.
    """

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
        ForeignKey("pricing_models.id", ondelete="NO ACTION"), index=True
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
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
