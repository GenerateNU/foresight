"""Flight arrivals per airport per day."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class FlightArrival(Base):
    """How many people are flying in on a given day."""

    __tablename__ = "flight_arrivals"

    id: Mapped[int] = mapped_column(primary_key=True)
    airport: Mapped[str] = mapped_column(String(10))  # "DUB"
    arrival_date: Mapped[date] = mapped_column(Date)

    flight_count: Mapped[int | None]
    avg_fare_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    source: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # CSO, OpenSky and AeroDataBox measure the same day at different grains, so
    # each keeps its own row and the read layer picks which one wins.
    __table_args__ = (UniqueConstraint("airport", "arrival_date", "source"),)
