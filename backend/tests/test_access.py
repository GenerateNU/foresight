from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from foresight.database.enums import JobKind
from foresight.database.models import PricingModel
from foresight.main import app
from foresight.repository import job as job_repo
from foresight.repository import user as user_repo
from foresight.services.domain import city as city_service
from foresight.services.domain import hotel as hotel_service
from foresight.services.domain import user as user_service
from tests.test_user import make_hotel, unique, unique_email

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from foresight.database.models import Hotel, User

ID_PARAMS = ("hotel_id", "job_id", "model_id", "room_type_id")
ROUTES = [
    (method.upper(), path)
    for path, operations in app.openapi()["paths"].items()
    for method in operations
    if path != "/health" and not path.startswith("/auth/")
]
SCOPED = [
    route for route in ROUTES if any(f"{{{name}}}" in route[1] for name in ID_PARAMS)
]


def route_ids(routes: list[tuple[str, str]]) -> list[str]:
    return [f"{method} {path}" for method, path in routes]


async def make_user(session: AsyncSession) -> User:
    return await user_service.sign_in(
        session,
        google_id=unique("google"),
        email=unique_email(),
        email_verified=True,
        name=None,
    )


async def make_hotel_with_data(session: AsyncSession, user: User | None) -> dict:
    hotel = await make_hotel(session)
    if user is not None:
        await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)
    job = await job_repo.create_job(
        session, hotel_id=hotel.id, kind=JobKind.WEATHER, params={}
    )
    model = PricingModel(
        hotel_id=hotel.id,
        version=1,
        algorithm="ebm",
        artifact=b"not a real model",
        features=[],
        metrics={},
        lib_versions={},
        data_start=date(2025, 1, 1),
        data_end=date(2025, 12, 31),
        is_active=False,
    )
    session.add(model)
    room_type = await hotel_service.create_room_type(
        session, hotel.id, name=unique("Room"), room_count=5, base_rate=Decimal("100")
    )
    await session.flush()
    return {
        "hotel": hotel,
        "hotel_id": hotel.id,
        "job_id": job.id,
        "model_id": model.id,
        "room_type_id": room_type.id,
    }


def fill(path: str, ids: dict) -> str:
    return path.format(**{name: ids[name] for name in ID_PARAMS})


def test_every_kind_of_hotel_id_is_covered() -> None:
    assert all(any(f"{{{name}}}" in path for _, path in SCOPED) for name in ID_PARAMS)


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=route_ids(ROUTES))
async def test_every_route_needs_a_login(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, re.sub(r"\{[^}]+\}", "1", path))

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), SCOPED, ids=route_ids(SCOPED))
async def test_another_hotels_data_is_404(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
    method: str,
    path: str,
) -> None:
    user = await make_user(session)
    await make_hotel_with_data(session, user)
    theirs = await make_hotel_with_data(session, None)
    sign_in_as(user)

    response = await client.request(method, fill(path, theirs))

    assert response.status_code == 404


READS = [route for route in SCOPED if route[0] == "GET"]


@pytest.mark.parametrize(("method", "path"), READS, ids=route_ids(READS))
async def test_own_hotels_data_is_not_404(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
    method: str,
    path: str,
) -> None:
    user = await make_user(session)
    mine = await make_hotel_with_data(session, user)
    sign_in_as(user)

    response = await client.request(method, fill(path, mine))

    assert response.status_code != 404


async def test_hotels_lists_only_the_users_own(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
) -> None:
    user, stranger = await make_user(session), await make_user(session)
    mine = await make_hotel_with_data(session, user)
    await make_hotel_with_data(session, None)

    sign_in_as(user)
    own = await client.get("/hotels")
    sign_in_as(stranger)
    none = await client.get("/hotels")

    assert [h["id"] for h in own.json()] == [mine["hotel_id"]]
    assert none.json() == []


async def test_creating_a_hotel_links_its_creator(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
) -> None:
    creator, other = await make_user(session), await make_user(session)
    city = await city_service.create_city(
        session,
        name=unique("City"),
        timezone="Europe/Dublin",
        latitude=53.35,
        longitude=-6.26,
    )

    sign_in_as(creator)
    created = await client.post(
        "/hotels", json={"name": "New Hotel", "city_id": city.id, "total_rooms": 10}
    )
    hotel_id = created.json()["id"]
    mine = await client.get(f"/hotels/{hotel_id}")
    sign_in_as(other)
    theirs = await client.get(f"/hotels/{hotel_id}")

    assert created.status_code == 201
    assert mine.status_code == 200
    assert theirs.status_code == 404


async def test_a_city_can_be_changed_only_by_someone_in_it(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
) -> None:
    worker, stranger = await make_user(session), await make_user(session)
    hotel: Hotel = (await make_hotel_with_data(session, worker))["hotel"]
    url = f"/cities/{hotel.city_id}"
    rename = {"name": unique("Renamed")}

    sign_in_as(stranger)
    listed = await client.get("/cities")
    read = await client.get(url)
    denied = await client.patch(url, json=rename)
    sign_in_as(worker)
    allowed = await client.patch(url, json=rename)

    assert listed.status_code == read.status_code == 200
    assert denied.status_code == 404
    assert allowed.status_code == 200


async def test_a_member_links_a_colleague_by_email(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
) -> None:
    member, colleague = await make_user(session), await make_user(session)
    mine = await make_hotel_with_data(session, member)
    url = f"/hotels/{mine['hotel_id']}/users"

    sign_in_as(member)
    first = await client.post(url, json={"email": colleague.email})
    second = await client.post(url, json={"email": colleague.email})
    sign_in_as(colleague)
    listed = await client.get("/hotels")

    assert (first.status_code, second.status_code) == (204, 204)
    assert [h["id"] for h in listed.json()] == [mine["hotel_id"]]


async def test_a_non_member_cannot_link_anyone(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
) -> None:
    stranger, colleague = await make_user(session), await make_user(session)
    theirs = await make_hotel_with_data(session, None)

    sign_in_as(stranger)
    response = await client.post(
        f"/hotels/{theirs['hotel_id']}/users", json={"email": colleague.email}
    )

    assert response.status_code == 404
    assert await user_repo.list_hotel_ids(session, colleague.id) == []


async def test_linking_an_unknown_or_shared_email_fails(
    client: AsyncClient,
    session: AsyncSession,
    sign_in_as: Callable[[User | None], None],
) -> None:
    member = await make_user(session)
    mine = await make_hotel_with_data(session, member)
    shared = unique_email()
    for _ in range(2):
        await user_service.sign_in(
            session,
            google_id=unique("google"),
            email=shared,
            email_verified=True,
            name=None,
        )
    url = f"/hotels/{mine['hotel_id']}/users"

    sign_in_as(member)
    unknown = await client.post(url, json={"email": unique_email()})
    ambiguous = await client.post(url, json={"email": shared})

    assert unknown.status_code == 404
    assert ambiguous.status_code == 409
