from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class Booking(Base):
    """One booked room, from Guestline's Daily New Reservations.

    BK100014/2 is the second room of BK100014. The report lists only bookings
    still live when it's exported, and a later cancellation isn't read, so a
    row stays once loaded. Times are the hotel's local time; money is before
    VAT.

    Attributes:
        id (int): Primary key.
        hotel_id (int): The hotel.
        book_ref (str): Guestline's reference for the room.
        booked_at (datetime): When it was booked.
        arrival (date): First night.
        departure (date): The morning after the last night.
        nights (int): Nights booked.
        room_type_code (str): Guestline's room code, e.g. DOUBLE.
        company_code (str | None): The company's code, if any.
        agent_code (str | None): The agent's code, if any.
        adr_nett (Decimal): Average rate per night, before VAT.
        value_nett (Decimal): Value of the whole stay, before VAT.
        rate_plan (str | None): Guestline's rate plan, e.g. BAR_RO.
        market_segment (str | None): Guestline's market segment.
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    book_ref: Mapped[str] = mapped_column(String(32))
    booked_at: Mapped[datetime] = mapped_column(DateTime)
    arrival: Mapped[date] = mapped_column(Date)
    departure: Mapped[date] = mapped_column(Date)
    nights: Mapped[int]
    room_type_code: Mapped[str] = mapped_column(String(32))
    company_code: Mapped[str | None] = mapped_column(String(64))
    agent_code: Mapped[str | None] = mapped_column(String(64))
    adr_nett: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    value_nett: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    rate_plan: Mapped[str | None] = mapped_column(String(64))
    market_segment: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("hotel_id", "book_ref"),)
