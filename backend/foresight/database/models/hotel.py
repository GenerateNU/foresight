"""A hotel, its room types, and how each room type sold per night."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from foresight.database.base import Base


class Hotel(Base):
    """A property we price for."""

    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120))
    total_rooms: Mapped[int]

    # Used to measure distance to event venues.
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    # The hotel's main airport, used to look up flight arrivals. Both codes are
    # stored because flight sources use different ones.
    airport_iata: Mapped[str | None] = mapped_column(String(3))  # "DUB"
    airport_icao: Mapped[str | None] = mapped_column(String(4))  # "EIDW"

    # IANA zone, e.g. "Europe/Dublin". Stay nights are local to the hotel, so
    # sources reporting UTC instants (OpenSky) are bucketed into days with it.
    timezone: Mapped[str | None] = mapped_column(String(64))

    room_types: Mapped[list["RoomType"]] = relationship(
        back_populates="hotel", lazy="raise", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("name", "city"),)


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
