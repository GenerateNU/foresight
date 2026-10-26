"""Daily weather per city: forecasts and recorded actuals."""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class Weather(Base):
    """Daily weather for a city.

    Rows are either a forecast (is_forecast=True, may be revised) or a recorded
    actual (is_forecast=False, final).
    """

    __tablename__ = "weather"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"))
    weather_date: Mapped[date] = mapped_column(Date)  # the day being described

    temp_max_c: Mapped[float | None]
    temp_min_c: Mapped[float | None]
    precip_mm: Mapped[float | None]
    wind_kph: Mapped[float | None]
    condition: Mapped[str | None] = mapped_column(String(60))  # "rain", "cloudy", ...

    is_forecast: Mapped[bool]
    source: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # A forecast and the recorded actual for the same day are different rows, as
    # are two sources' readings; re-fetching either one updates in place.
    __table_args__ = (
        UniqueConstraint("city_id", "weather_date", "is_forecast", "source"),
    )
