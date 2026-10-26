"""What competing hotels charge per night."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class CompetitorRate(Base):
    """What another hotel is charging for a given night."""

    __tablename__ = "competitor_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_name: Mapped[str] = mapped_column(String(200))  # the competitor
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"))

    stay_date: Mapped[date] = mapped_column(Date)  # the night being priced
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # null if sold out
    is_sold_out: Mapped[bool] = mapped_column(default=False)

    source: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("city_id", "hotel_name", "stay_date", "source"),)
