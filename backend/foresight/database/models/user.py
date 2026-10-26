"""A person who signs in with Google, and the hotels they work for."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class User(Base):
    """One Google account. Created the first time someone signs in, so a user
    may have no hotel yet.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Google's account id (the `sub` claim). This is the identity: an email can
    # change, the id can't.
    google_id: Mapped[str] = mapped_column(String(255), unique=True)
    # Not unique: an address can pass to another person before its previous
    # owner signs in again and the row is updated.
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # A row only exists because they just signed in, so it starts at creation.
    last_signed_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserHotel(Base):
    """A user works for a hotel. A hotel has several users and a user can belong
    to several hotels. Deleting either side removes the link.
    """

    __tablename__ = "user_hotels"

    # The composite key rejects a second link for the same pair, and its leading
    # column serves as the foreign key index for user_id.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
