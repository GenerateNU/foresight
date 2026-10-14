"""A city we sell rooms in: the market every outside signal is keyed on."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class City(Base):
    """One market. Hotels belong to it; weather, events, flights and competitor
    rates are recorded against it and shared by every hotel in it.
    """

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))  # "Dublin"
    # Normalized name (`services/adapters/normalize.slugify_city`). Unique, so
    # "Dublin" and "dublin " can't become two markets. Also part of every
    # event's dedupe key.
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    country: Mapped[str | None] = mapped_column(String(2))  # ISO-3166 alpha-2

    # IANA zone, e.g. "Europe/Dublin". Stay nights are local, so weather days,
    # event dates and flight arrivals are all bucketed with it.
    timezone: Mapped[str] = mapped_column(String(64))

    # The centre of the market: where weather is read and events are searched.
    latitude: Mapped[float]
    longitude: Mapped[float]

    # The main airport. Both codes are stored because flight sources differ.
    airport_iata: Mapped[str | None] = mapped_column(String(3))  # "DUB"
    airport_icao: Mapped[str | None] = mapped_column(String(4))  # "EIDW"
