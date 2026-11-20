"""A hotel and its room types."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from foresight.database.base import Base

if TYPE_CHECKING:
    from foresight.database.models.city import City


class Hotel(Base):
    """A property we price for."""

    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Its market. Timezone and every outside signal come from here.
    # RESTRICT: a city can't be deleted while hotels are in it.
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))

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

    hotel: Mapped["Hotel"] = relationship(back_populates="room_types", lazy="raise")

    # Leads on hotel_id, so it also serves as the foreign key index.
    __table_args__ = (UniqueConstraint("hotel_id", "name"),)
