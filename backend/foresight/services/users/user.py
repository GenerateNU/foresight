from sqlalchemy.ext.asyncio import AsyncSession

from foresight.config import settings
from foresight.database.models.user import User
from foresight.repository import user as user_repo
from foresight.services.errors import (
    ConflictError,
    ForbiddenError,
    NotConfiguredError,
    NotFoundError,
    NotSignedInError,
)
from foresight.services.hotels.hotel import get_hotel


def require_sign_in_configured() -> None:
    """Checks every Google and session setting sign-in needs is set.

    Raises:
        NotConfiguredError: Naming the settings that are missing.
    """
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("SESSION_SECRET", settings.session_secret),
        )
        if not value
    ]
    if missing:
        raise NotConfiguredError(f"{', '.join(missing)} not set on the server")


async def sign_in(
    session: AsyncSession,
    *,
    google_id: str | None,
    email: str | None,
    email_verified: bool,
    name: str | None,
) -> User:
    """Finds or creates the user for a Google account and records the sign-in.

    Args:
        session (AsyncSession): The database session.
        google_id (str | None): Google's account id.
        email (str | None): The account's email.
        email_verified (bool): Whether Google verified the email.
        name (str | None): The account's display name.

    Returns:
        User: The signed-in user.

    Raises:
        ForbiddenError: Google gave no id or email, or didn't verify it.
    """
    if not google_id or not email or not email_verified:
        raise ForbiddenError("Google did not confirm a verified email for this account")
    return await user_repo.upsert_user(
        session, google_id=google_id, email=email, name=name
    )


async def get_signed_in_user(session: AsyncSession, user_id: object) -> User:
    """Gets the user a session belongs to.

    Args:
        session (AsyncSession): The database session.
        user_id (object): The id stored in the session cookie, unchecked.

    Returns:
        User: The user.

    Raises:
        NotSignedInError: The id isn't an int, or no such user exists.
    """
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise NotSignedInError("Not signed in")
    user = await user_repo.get_user(session, user_id)
    if user is None:
        raise NotSignedInError("Not signed in")
    return user


async def get_user(session: AsyncSession, user_id: int) -> User:
    """Gets a user.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.

    Returns:
        User: The user.

    Raises:
        NotFoundError: The user doesn't exist.
    """
    user = await user_repo.get_user(session, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User:
    """Gets the user with an email, ignoring case.

    Args:
        session (AsyncSession): The database session.
        email (str): The email.

    Returns:
        User: The user.

    Raises:
        NotFoundError: No user has this email.
        ConflictError: Several do. Emails change hands, so this never picks
            one: it would give a hotel's access to the wrong person.
    """
    users = await user_repo.list_users_by_email(session, email)
    if not users:
        raise NotFoundError("User", email)
    if len(users) > 1:
        raise ConflictError(f"More than one user has the email {email!r}")
    return users[0]


async def link_user_to_hotel(
    session: AsyncSession, *, user_id: int, hotel_id: int
) -> bool:
    """Links a user to a hotel; linking twice is not an error.

    Args:
        session (AsyncSession): The database session.
        user_id (int): The user.
        hotel_id (int): The hotel.

    Returns:
        bool: True if the link is new, False if it already existed.

    Raises:
        NotFoundError: Unknown user or hotel.
    """
    await get_user(session, user_id)
    await get_hotel(session, hotel_id)
    return await user_repo.link_hotel(session, user_id=user_id, hotel_id=hotel_id)


async def link_user_by_email(
    session: AsyncSession, *, hotel_id: int, email: str
) -> bool:
    """Links the user with an email to a hotel.

    The caller has checked that whoever is linking may reach the hotel.

    Args:
        session (AsyncSession): The database session.
        hotel_id (int): The hotel.
        email (str): The user's email.

    Returns:
        bool: True if the link is new, False if it already existed.

    Raises:
        NotFoundError: Nobody with this email has signed in yet, or the hotel
            is unknown.
        ConflictError: Several users share the email.
    """
    user = await get_user_by_email(session, email)
    return await link_user_to_hotel(session, user_id=user.id, hotel_id=hotel_id)
