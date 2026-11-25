from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from foresight.database.base import Base
from foresight.database.models.city import City


class Hotel(Base):
    """A hotel we price for.

    Attributes:
        id (int): Primary key.
        name (str): The hotel's name; unique within its city.
        city_id (int): Its market. A city can't be deleted while it has hotels.
        latitude (float | None): The hotel itself, for distance to venues.
        longitude (float | None): The hotel itself, for distance to venues.
        city (City): The city, loaded with the hotel.
        room_types (list[RoomType]): Its room types.
    """

    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    city: Mapped["City"] = relationship(lazy="raise")
    room_types: Mapped[list["RoomType"]] = relationship(
        back_populates="hotel", lazy="raise", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("city_id", "name"),)


class RoomType(Base):
    """A room type the model prices, named after Guestline's room code.

    Attributes:
        id (int): Primary key.
        hotel_id (int): The hotel.
        name (str): The room code, e.g. DOUBLE; unique within the hotel.
        hotel (Hotel): The hotel.
    """

    __tablename__ = "room_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))

    hotel: Mapped["Hotel"] = relationship(back_populates="room_types", lazy="raise")

    __table_args__ = (UniqueConstraint("hotel_id", "name"),)
