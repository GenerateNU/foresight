from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class City(Base):
    """One market: its hotels share its events, timezone and centre.

    Attributes:
        id (int): Primary key.
        name (str): The city's name, e.g. "Dublin".
        slug (str): The normalized name; unique, so "Dublin" and "dublin "
            can't become two markets. Part of every event's dedupe key.
        country (str | None): ISO-3166 alpha-2 code.
        timezone (str): IANA timezone. Stay nights and event dates are local
            to it.
        latitude (float): The centre of the market, where events are searched.
        longitude (float): The centre of the market, where events are searched.
    """

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    country: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[float]
    longitude: Mapped[float]
