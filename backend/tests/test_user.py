"""Tests for users and their hotel links, at the repository and service layers.

Need a migrated database (`just migrate`; CI migrates before it runs pytest).
The `session` fixture (conftest.py) runs each test inside a transaction that is
rolled back, so it leaves nothing behind. Names, emails and Google ids carry a
random suffix, so a test can't collide with rows already in the database it
runs against.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from foresight.repository import user as user_repo
from foresight.services.domain import city as city_service
from foresight.services.domain import hotel as hotel_service
from foresight.services.domain import user as user_service
from foresight.services.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models.hotel import Hotel

# Far above any id a sequence will reach.
MISSING_ID = 2_000_000_000


# Builders


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def unique_email() -> str:
    return f"{unique('person')}@example.com"


async def make_hotel(session: AsyncSession) -> Hotel:
    """A hotel in a city of its own."""
    city = await city_service.create_city(
        session,
        name=unique("Testville"),
        timezone="Europe/Dublin",
        latitude=53.35,
        longitude=-6.26,
    )
    return await hotel_service.create_hotel(
        session,
        name=unique("Test Hotel"),
        city_id=city.id,
        total_rooms=10,
        latitude=None,
        longitude=None,
    )


# Repository


async def test_create_user_stores_the_google_identity(session: AsyncSession) -> None:
    google_id, email = unique("google"), unique_email()

    user = await user_repo.create_user(
        session, google_id=google_id, email=email, name="Ada Lovelace"
    )

    assert user is not None
    assert (user.google_id, user.email, user.name) == (google_id, email, "Ada Lovelace")
    assert user.created_at is not None
    assert user.last_signed_in_at is not None


async def test_new_user_has_no_hotels(session: AsyncSession) -> None:
    user = await user_repo.create_user(
        session, google_id=unique("google"), email=unique_email(), name=None
    )

    assert user is not None
    assert await user_repo.list_hotel_ids(session, user.id) == []


async def test_create_user_returns_none_for_a_known_google_id(
    session: AsyncSession,
) -> None:
    google_id = unique("google")
    await user_repo.create_user(
        session, google_id=google_id, email=unique_email(), name=None
    )

    again = await user_repo.create_user(
        session, google_id=google_id, email=unique_email(), name=None
    )

    assert again is None


async def test_get_user_by_google_id(session: AsyncSession) -> None:
    google_id = unique("google")
    created = await user_repo.create_user(
        session, google_id=google_id, email=unique_email(), name=None
    )

    found = await user_repo.get_user_by_google_id(session, google_id)

    assert created is not None
    assert found is not None
    assert found.id == created.id
    assert await user_repo.get_user_by_google_id(session, unique("google")) is None


async def test_users_are_found_by_email_ignoring_case(session: AsyncSession) -> None:
    email = f"Ada.{unique('x')}@Example.com"
    created = await user_repo.create_user(
        session, google_id=unique("google"), email=email, name=None
    )

    assert created is not None
    for query in (email.lower(), email.upper()):
        found = await user_repo.list_users_by_email(session, query)
        assert [u.id for u in found] == [created.id]


async def test_link_hotel_twice_keeps_one_link(session: AsyncSession) -> None:
    user = await user_repo.create_user(
        session, google_id=unique("google"), email=unique_email(), name=None
    )
    hotel = await make_hotel(session)
    assert user is not None

    first = await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)
    second = await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)

    assert (first, second) == (True, False)
    assert await user_repo.list_hotel_ids(session, user.id) == [hotel.id]


async def test_user_can_belong_to_several_hotels(session: AsyncSession) -> None:
    user = await user_repo.create_user(
        session, google_id=unique("google"), email=unique_email(), name=None
    )
    hotels = [await make_hotel(session), await make_hotel(session)]
    assert user is not None

    for hotel in hotels:
        await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)

    assert await user_repo.list_hotel_ids(session, user.id) == sorted(
        h.id for h in hotels
    )


async def test_hotel_can_have_several_users(session: AsyncSession) -> None:
    hotel = await make_hotel(session)

    for _ in range(2):
        user = await user_repo.create_user(
            session, google_id=unique("google"), email=unique_email(), name=None
        )
        assert user is not None
        assert await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)
        assert await user_repo.list_hotel_ids(session, user.id) == [hotel.id]


# Service


async def test_create_user_then_find_by_google_id(session: AsyncSession) -> None:
    google_id = unique("google")
    created = await user_service.create_user(
        session, google_id=google_id, email=unique_email(), name="Ada Lovelace"
    )

    found = await user_service.get_user_by_google_id(session, google_id)

    assert found.id == created.id
    assert found.name == "Ada Lovelace"


async def test_create_user_for_a_known_google_account_conflicts(
    session: AsyncSession,
) -> None:
    google_id = unique("google")
    await user_service.create_user(
        session, google_id=google_id, email=unique_email(), name=None
    )

    with pytest.raises(ConflictError):
        await user_service.create_user(
            session, google_id=google_id, email=unique_email(), name=None
        )


async def test_unknown_google_id_is_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await user_service.get_user_by_google_id(session, unique("google"))


async def test_link_user_to_hotel_is_idempotent(session: AsyncSession) -> None:
    user = await user_service.create_user(
        session, google_id=unique("google"), email=unique_email(), name=None
    )
    hotel = await make_hotel(session)

    first = await user_service.link_user_to_hotel(
        session, user_id=user.id, hotel_id=hotel.id
    )
    second = await user_service.link_user_to_hotel(
        session, user_id=user.id, hotel_id=hotel.id
    )

    assert (first, second) == (True, False)
    assert await user_service.list_hotel_ids(session, user.id) == [hotel.id]


async def test_link_needs_an_existing_user_and_hotel(session: AsyncSession) -> None:
    user = await user_service.create_user(
        session, google_id=unique("google"), email=unique_email(), name=None
    )
    hotel = await make_hotel(session)

    with pytest.raises(NotFoundError):
        await user_service.link_user_to_hotel(
            session, user_id=MISSING_ID, hotel_id=hotel.id
        )
    with pytest.raises(NotFoundError):
        await user_service.link_user_to_hotel(
            session, user_id=user.id, hotel_id=MISSING_ID
        )
    assert await user_service.list_hotel_ids(session, user.id) == []


async def test_get_user_by_email_ignores_case(session: AsyncSession) -> None:
    email = f"Ada.{unique('x')}@Example.com"
    created = await user_service.create_user(
        session, google_id=unique("google"), email=email, name=None
    )

    found = await user_service.get_user_by_email(session, email.lower())

    assert found.id == created.id


async def test_unknown_email_is_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await user_service.get_user_by_email(session, unique_email())


async def test_shared_email_is_a_conflict_not_a_guess(session: AsyncSession) -> None:
    email = unique_email()
    for _ in range(2):
        await user_service.create_user(
            session, google_id=unique("google"), email=email, name=None
        )

    with pytest.raises(ConflictError):
        await user_service.get_user_by_email(session, email)
