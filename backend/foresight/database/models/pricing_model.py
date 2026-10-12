from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class PricingModel(Base):
    """One trained model version for a hotel.

    The fitted model is serialized to bytes in `artifact`. Only one version per
    hotel is active at a time
    """

    __tablename__ = "pricing_models"
    __table_args__ = (
        UniqueConstraint("hotel_id", "version"),
        # At most one active model per hotel.
        Index(
            "uq_pricing_models_active_per_hotel",
            "hotel_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    version: Mapped[int]  # increments per hotel
    algorithm: Mapped[str] = mapped_column(String(60))  # e.g. "ebm"

    # Serialized fitted model. Only load artifacts our own training wrote.
    artifact: Mapped[bytes] = mapped_column(LargeBinary)

    features: Mapped[list[str]] = mapped_column(JSONB)  # input columns, in order
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)  # mae, rmse, r2, ...
    lib_versions: Mapped[dict[str, str]] = mapped_column(JSONB)  # pickle compat

    # Training window (stay dates).
    data_start: Mapped[date] = mapped_column(Date)
    data_end: Mapped[date] = mapped_column(Date)

    is_active: Mapped[bool] = mapped_column(default=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
