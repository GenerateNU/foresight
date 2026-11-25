from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from foresight.database.base import Base


class User(Base):
    """One Google account, created the first time someone signs in.

    Attributes:
        id (int): Primary key.
        google_id (str): Google's account id (the `sub` claim); the identity,
            since an email can change.
        email (str): Not unique: an address can pass to someone else before
            its previous owner signs in again.
        name (str | None): The name Google gave.
        created_at (datetime): When they first signed in.
        last_signed_in_at (datetime): When they last signed in.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_signed_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserHotel(Base):
    """A user works for a hotel; deleting either removes the link.

    Attributes:
        user_id (int): The user.
        hotel_id (int): The hotel.
        created_at (datetime): When they were linked.
    """

    __tablename__ = "user_hotels"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
