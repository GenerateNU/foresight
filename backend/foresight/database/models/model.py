from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class PricingModel(Base):
    """One trained model version for a hotel; at most one is active.

    Attributes:
        id (int): Primary key.
        hotel_id (int): The hotel.
        version (int): Counts up per hotel, from 1.
        algorithm (str): `ebm`, or `ebm-tuned` for a tune-up.
        room_type_id (int | None): The room type it prices; a tune-up has its
            base's. Null for versions that predate the main room type, which
            can't serve.
        base_model_id (int | None): For a tune-up, the version it corrects;
            its artifact holds only the correction. A base can't be deleted
            while a tune-up points to it.
        description (str | None): What this version tried.
        artifact (bytes): The serialized model. Only load artifacts our own
            training wrote: unpickling can run code.
        features (list[str]): Its input columns, in order.
        metrics (dict[str, Any]): What it trained on and what the fit cost.
        lib_versions (dict[str, str]): Library versions, to load the artifact.
        data_start (date): First night trained on.
        data_end (date): Last night trained on.
        is_active (bool): Whether it serves the hotel.
        trained_at (datetime): When it was saved.
    """

    __tablename__ = "pricing_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    version: Mapped[int]
    algorithm: Mapped[str] = mapped_column(String(60))
    room_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("room_types.id", ondelete="CASCADE"), index=True
    )
    base_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("pricing_models.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    artifact: Mapped[bytes] = mapped_column(LargeBinary)
    features: Mapped[list[str]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    lib_versions: Mapped[dict[str, str]] = mapped_column(JSONB)
    data_start: Mapped[date] = mapped_column(Date)
    data_end: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("hotel_id", "version"),
        Index(
            "uq_pricing_models_active_per_hotel",
            "hotel_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
