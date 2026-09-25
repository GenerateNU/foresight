"""External factors: weather, events, competitor pricing, flights."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Weather(Base):
    """Daily weather for a city.

    Rows are either a forecast (is_forecast=True, may be revised) or a recorded
    actual (is_forecast=False, final).
    """

    __tablename__ = "weather"

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(120))
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


class Event(Base):
    """Something happening nearby that drives demand."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(60))
    venue: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120))

    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    expected_attendance: Mapped[int | None]

    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    source: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CompetitorRate(Base):
    """What another hotel is charging for a given night."""

    __tablename__ = "competitor_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_name: Mapped[str] = mapped_column(String(200))  # the competitor
    city: Mapped[str] = mapped_column(String(120))

    stay_date: Mapped[date] = mapped_column(Date)  # the night being priced
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # null if sold out
    is_sold_out: Mapped[bool] = mapped_column(default=False)

    source: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
