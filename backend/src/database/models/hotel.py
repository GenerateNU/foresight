"""Hotel data."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120))
    total_rooms: Mapped[int]

    # Used to measure distance to event venues.
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    room_types: Mapped[list["RoomType"]] = relationship(back_populates="hotel")


class RoomType(Base):
    """A category of room, e.g. "Deluxe King". Price is set per room type."""

    __tablename__ = "room_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"))
    name: Mapped[str] = mapped_column(String(120))
    room_count: Mapped[int]  # how many physical rooms of this type
    base_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # normal price

    hotel: Mapped["Hotel"] = relationship(back_populates="room_types")
    nights: Mapped[list["DailyPerformance"]] = relationship(back_populates="room_type")


class DailyPerformance(Base):
    """One room type, one night: what we charged and how it sold."""

    __tablename__ = "daily_performance"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id"))

    stay_date: Mapped[date] = mapped_column(Date)  # the night being sold
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # price we listed
    rooms_available: Mapped[int]
    rooms_sold: Mapped[int] = mapped_column(default=0)
    room_revenue: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    room_type: Mapped["RoomType"] = relationship(back_populates="nights")

    # One row per room type per night.
    __table_args__ = (UniqueConstraint("room_type_id", "stay_date"),)
