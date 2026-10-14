"""A hotel, its room types, and how each room type sold per night."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from foresight.database.base import Base

if TYPE_CHECKING:
    from foresight.database.models.city import City


class Hotel(Base):
    """A property we price for."""

    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Its market. Timezone, airport and every outside signal come from here.
    # RESTRICT: a city can't be deleted while hotels are in it.
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    total_rooms: Mapped[int]

    # The hotel's own location, for distance to event venues. The city's
    # centre is used for searching.
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    city: Mapped["City"] = relationship(lazy="raise")
    room_types: Mapped[list["RoomType"]] = relationship(
        back_populates="hotel", lazy="raise", passive_deletes=True
    )

    # Leads on city_id, so it also serves as the foreign key index.
    __table_args__ = (UniqueConstraint("city_id", "name"),)


class RoomType(Base):
    """A category of room, e.g. "Deluxe King". Price is set per room type."""

    __tablename__ = "room_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    room_count: Mapped[int]  # how many physical rooms of this type
    base_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # normal price

    hotel: Mapped["Hotel"] = relationship(back_populates="room_types", lazy="raise")
    nights: Mapped[list["DailyPerformance"]] = relationship(
        back_populates="room_type", lazy="raise", passive_deletes=True
    )

    # Leads on hotel_id, so it also serves as the foreign key index.
    __table_args__ = (UniqueConstraint("hotel_id", "name"),)


class DailyPerformance(Base):
    """One room type, one night: what we charged and how it sold."""

    __tablename__ = "daily_performance"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.id", ondelete="CASCADE")
    )

    stay_date: Mapped[date] = mapped_column(Date)  # the night being sold
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # price we listed
    rooms_available: Mapped[int]
    rooms_sold: Mapped[int] = mapped_column(default=0)
    room_revenue: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    room_type: Mapped["RoomType"] = relationship(back_populates="nights", lazy="raise")

    # One row per room type per night. Also serves as the foreign key index.
    __table_args__ = (UniqueConstraint("room_type_id", "stay_date"),)
