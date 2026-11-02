"""Rooms booked and cancelled at a hotel, from its Guestline exports.

Guestline lists live bookings and cancelled ones in separate reports, so the two
tables are linked by `book_ref`, not a foreign key. Because uploads overlap, a
booking stored as live can later show up as cancelled too: a booking is only
live if it has no cancellation.

Times are the hotel's local time. Money is nett (before 13.5% VAT).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class Booking(Base):
    """One room on a live booking, e.g. BK100014/2 is the second room of BK100014."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    book_ref: Mapped[str] = mapped_column(String(32))
    booked_at: Mapped[datetime] = mapped_column(DateTime)
    arrival: Mapped[date] = mapped_column(Date)
    departure: Mapped[date] = mapped_column(Date)
    nights: Mapped[int]
    room_type_code: Mapped[str] = mapped_column(
        String(32)
    )  # Guestline's code, e.g. DOUBLE
    company_code: Mapped[str | None] = mapped_column(String(64))
    agent_code: Mapped[str | None] = mapped_column(String(64))
    adr_nett: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    value_nett: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    rate_plan: Mapped[str | None] = mapped_column(String(64))
    market_segment: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("hotel_id", "book_ref"),)


class BookingCancellation(Base):
    """One cancelled room. `book_ref` is the booking it cancelled."""

    __tablename__ = "booking_cancellations"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    cancel_ref: Mapped[str] = mapped_column(String(32))
    book_ref: Mapped[str] = mapped_column(String(32), index=True)
    booked_at: Mapped[datetime] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime] = mapped_column(DateTime)
    reason_code: Mapped[str | None] = mapped_column(String(32))
    arrival: Mapped[date] = mapped_column(Date)
    departure: Mapped[date] = mapped_column(Date)
    lost_revenue: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    __table_args__ = (UniqueConstraint("hotel_id", "cancel_ref"),)
