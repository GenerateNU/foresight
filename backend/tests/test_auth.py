from __future__ import annotations

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import itsdangerous.timed
import pytest
from httpx import ASGITransport, AsyncClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from pydantic import ValidationError

from foresight.config import Settings, settings
from foresight.database.session import get_session
from foresight.main import app
from foresight.repository import user as user_repo
from foresight.routes.auth import oauth
from foresight.services.domain import user as user_service
from foresight.services.errors import ForbiddenError, NotSignedInError
from tests.test_user import MISSING_ID, make_hotel, unique, unique_email

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from httpx import Response
    from sqlalchemy.ext.asyncio import AsyncSession

KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
METADATA = {
    "issuer": "https://accounts.google.com",
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    "jwks": KeySet([KEY]).as_dict(),
}


@pytest.fixture
async def client(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    async def load_server_metadata() -> dict[str, Any]:
        return METADATA

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    monkeypatch.setattr(oauth.google, "client_id", "test-client-id")
    monkeypatch.setattr(oauth.google, "load_server_metadata", load_server_metadata)
    app.dependency_overrides[get_session] = test_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


def id_token(
    nonce: str, claims: dict[str, Any] | None = None, key: RSAKey = KEY
) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "sub": unique("google"),
        "email": unique_email(),
        "email_verified": True,
        "name": "Ada Lovelace",
        "iat": now,
        "exp": now + 3600,
        "nonce": nonce,
    }
    return jwt.encode(
        {"alg": "RS256", "kid": "test-key"}, payload | (claims or {}), key
    )


async def google_sign_in(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, Any] | None = None,
    key: RSAKey = KEY,
) -> Response:
    login = await client.get("/auth/google/login")
    params = parse_qs(urlsplit(login.headers["location"]).query)
    token = id_token(params["nonce"][0], claims, key)

    async def fetch_access_token(**_: Any) -> dict[str, str]:
        return {"access_token": "access", "id_token": token}

    monkeypatch.setattr(oauth.google, "fetch_access_token", fetch_access_token)
    return await client.get(
        "/auth/google/callback",
        params={"code": "code", "state": params["state"][0]},
    )


async def test_sign_in_creates_then_refreshes_one_user(session: AsyncSession) -> None:
    google_id = unique("google")
    first = await user_service.sign_in(
        session,
        google_id=google_id,
        email="old@example.com",
        email_verified=True,
        name="Old Name",
    )
    first.last_signed_in_at = datetime(2020, 1, 1, tzinfo=UTC)
    await session.flush()

    second = await user_service.sign_in(
        session,
        google_id=google_id,
        email="new@example.com",
        email_verified=True,
        name=None,
    )

    assert second.id == first.id
    assert (second.email, second.name) == ("new@example.com", None)
    assert second.last_signed_in_at > datetime(2020, 1, 1, tzinfo=UTC)
    assert await user_service.list_hotel_ids(session, second.id) == []


@pytest.mark.parametrize(
    ("google_id", "email", "email_verified"),
    [("g", "a@example.com", False), ("g", None, True), (None, "a@example.com", True)],
)
async def test_sign_in_needs_a_verified_email(
    session: AsyncSession,
    google_id: str | None,
    email: str | None,
    email_verified: bool,
) -> None:
    with pytest.raises(ForbiddenError):
        await user_service.sign_in(
            session,
            google_id=google_id,
            email=email,
            email_verified=email_verified,
            name=None,
        )


async def test_get_signed_in_user_needs_a_real_user_id(session: AsyncSession) -> None:
    user = await user_service.sign_in(
        session,
        google_id=unique("google"),
        email=unique_email(),
        email_verified=True,
        name=None,
    )

    assert (await user_service.get_signed_in_user(session, user.id)).id == user.id
    for user_id in (None, str(user.id), True, MISSING_ID):
        with pytest.raises(NotSignedInError):
            await user_service.get_signed_in_user(session, user_id)


def test_samesite_none_needs_a_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(
            _env_file=None, session_cookie_samesite="none", session_cookie_secure=False
        )


async def test_login_redirects_to_google_with_state_nonce_and_pkce(
    client: AsyncClient,
) -> None:
    response = await client.get("/auth/google/login")

    location = urlsplit(response.headers["location"])
    params = parse_qs(location.query)
    assert response.status_code == 302
    assert location.netloc == "accounts.google.com"
    assert params["client_id"] == ["test-client-id"]
    assert params["redirect_uri"] == [settings.google_redirect_uri]
    assert params["scope"] == ["openid email profile"]
    assert params["code_challenge_method"] == ["S256"]
    assert all(params[key][0] for key in ("state", "nonce", "code_challenge"))


async def test_signing_in_twice_keeps_one_user_and_sets_a_cookie(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    google_id = unique("google")

    first = await google_sign_in(client, monkeypatch, {"sub": google_id})
    user = await user_repo.get_user_by_google_id(session, google_id)
    second = await google_sign_in(
        client, monkeypatch, {"sub": google_id, "name": "Ada King"}
    )
    again = await user_repo.get_user_by_google_id(session, google_id)

    cookie = first.headers["set-cookie"].lower()
    assert first.status_code == second.status_code == 302
    assert first.headers["location"] == settings.frontend_url
    assert "httponly" in cookie
    assert f"max-age={settings.session_max_age_seconds}" in cookie
    assert user.id == again.id
    assert again.name == "Ada King"


@pytest.mark.parametrize(
    "query",
    [{"code": "code"}, {"code": "code", "state": "forged"}, {"error": "access_denied"}],
    ids=["no-state", "forged-state", "google-refused"],
)
async def test_callback_rejects_bad_state_and_refusals(
    client: AsyncClient, query: dict[str, str]
) -> None:
    await client.get("/auth/google/login")

    response = await client.get("/auth/google/callback", params=query)

    assert response.status_code == 400
    assert (await client.get("/auth/me")).status_code == 401


@pytest.mark.parametrize(
    ("claims", "key"),
    [
        ({"aud": "someone-else"}, KEY),
        ({"iss": "https://evil.example"}, KEY),
        ({"nonce": "not-ours"}, KEY),
        ({"exp": 1}, KEY),
        ({}, OTHER_KEY),
    ],
    ids=["audience", "issuer", "nonce", "expired", "signature"],
)
async def test_invalid_id_tokens_are_rejected(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, Any],
    key: RSAKey,
) -> None:
    response = await google_sign_in(client, monkeypatch, claims, key)

    assert response.status_code == 400
    assert (await client.get("/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "issuer", ["https://accounts.google.com", "accounts.google.com"]
)
async def test_both_google_issuer_spellings_sign_in(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, issuer: str
) -> None:
    response = await google_sign_in(client, monkeypatch, {"iss": issuer})

    assert response.status_code == 302
    assert (await client.get("/auth/me")).status_code == 200


async def test_unverified_email_is_forbidden(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    google_id = unique("google")

    response = await google_sign_in(
        client, monkeypatch, {"sub": google_id, "email_verified": False}
    )

    assert response.status_code == 403
    assert await user_repo.get_user_by_google_id(session, google_id) is None


async def test_sign_in_is_503_until_it_is_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "")

    assert (await client.get("/auth/google/login")).status_code == 503
    assert (await client.get("/auth/google/callback")).status_code == 503


async def test_me_returns_the_user_and_their_hotels(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    google_id, email = unique("google"), unique_email()
    await google_sign_in(client, monkeypatch, {"sub": google_id, "email": email})
    user = await user_repo.get_user_by_google_id(session, google_id)

    before = await client.get("/auth/me")
    hotel = await make_hotel(session)
    await user_repo.link_hotel(session, user_id=user.id, hotel_id=hotel.id)
    after = await client.get("/auth/me")

    assert before.json() == {
        "id": user.id,
        "email": email,
        "name": "Ada Lovelace",
        "hotels": [],
    }
    assert [h["id"] for h in after.json()["hotels"]] == [hotel.id]


async def test_me_without_a_session_is_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not signed in"}


async def test_logout_ends_the_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await google_sign_in(client, monkeypatch)
    assert (await client.get("/auth/me")).status_code == 200

    assert (await client.post("/auth/logout")).status_code == 204
    assert (await client.get("/auth/me")).status_code == 401


async def test_tampered_cookie_is_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await google_sign_in(client, monkeypatch)
    value = client.cookies["foresight_session"]
    tampered = value[:-1] + ("A" if value[-1] != "A" else "B")

    assert (await client.get("/auth/me")).status_code == 200
    response = await client.get(
        "/auth/me", headers={"Cookie": f"foresight_session={tampered}"}
    )
    assert response.status_code == 401


async def test_expired_cookie_is_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_ago = time.time() - settings.session_max_age_seconds - 60
    with monkeypatch.context() as past:
        past.setattr(itsdangerous.timed, "time", SimpleNamespace(time=lambda: long_ago))
        await google_sign_in(client, monkeypatch)

    assert (await client.get("/auth/me")).status_code == 401


async def test_only_the_frontend_may_send_credentials(client: AsyncClient) -> None:
    ask = {"Access-Control-Request-Method": "GET"}

    allowed = await client.options(
        "/auth/me", headers=ask | {"Origin": settings.frontend_origin}
    )
    other = await client.options(
        "/auth/me", headers=ask | {"Origin": "https://evil.example"}
    )

    assert allowed.headers["access-control-allow-origin"] == settings.frontend_origin
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in other.headers
