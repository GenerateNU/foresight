"""The recommendation range's limits."""

from __future__ import annotations

from foresight.services.domain import user as user_service
from tests.test_user import make_hotel, unique, unique_email


async def test_recommendations_reject_a_bad_range(client, session, sign_in_as) -> None:
    user = await user_service.sign_in(
        session,
        google_id=unique("google"),
        email=unique_email(),
        email_verified=True,
        name=None,
    )
    hotel = await make_hotel(session)
    await user_service.link_user_to_hotel(session, user_id=user.id, hotel_id=hotel.id)
    sign_in_as(user)

    base = f"/hotels/{hotel.id}/recommendations"
    too_long = await client.get(f"{base}?start=2025-01-01&end=2025-12-31")
    reversed_ = await client.get(f"{base}?start=2025-02-01&end=2025-01-01")
    both = await client.get(f"{base}?date=2025-01-01&start=2025-01-01")
    neither = await client.get(base)

    assert too_long.status_code == 422
    assert reversed_.status_code == 422
    assert both.status_code == 422
    assert neither.status_code == 422
