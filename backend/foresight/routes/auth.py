"""Signing in with Google, the session it starts, and who is signed in.

Google's authorization-code flow runs through Authlib, which keeps the flow's
state and nonce in the signed session cookie and verifies Google's ID token. The
OAuth client lives here rather than in `services/` because it reads and writes
the HTTP session; the service only gets plain values (decision 0040).

Nothing else requires a session yet: `CurrentUserDep` is what routes use once
they do.
"""

from typing import Annotated

from authlib.common.errors import AuthlibBaseError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import Field

from foresight.config import settings
from foresight.database.models.user import User
from foresight.routes.helpers import ResponseSchema, SessionDep
from foresight.routes.hotel import HotelResponse
from foresight.services.domain import hotel as hotel_service
from foresight.services.domain import user as user_service

router = APIRouter(prefix="/auth", tags=["Auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    # Where Google's endpoints, issuer and signing keys come from.
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)

# Google documents both spellings of its issuer; Authlib alone would accept only
# the one in its discovery document.
_GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


# Schemas


class MeResponse(ResponseSchema):
    id: int = Field(description="The user's id")
    email: str = Field(description="The email Google last reported for the account")
    name: str | None = Field(description="Their name on Google; null if it has none")
    hotels: list[HotelResponse] = Field(
        description="The hotels they work for; empty until an operator links one"
    )


# Dependencies


async def get_current_user(request: Request, session: SessionDep) -> User:
    """The signed-in user. A missing, expired or tampered cookie arrives here as
    an empty session, so every case is the same 401."""
    return await user_service.get_signed_in_user(
        session, request.session.get("user_id")
    )


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# Endpoints


@router.get(
    "/google/login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={503: {"description": "Google sign-in isn't configured on the server"}},
)
async def google_login(request: Request) -> RedirectResponse:
    """Send the browser to Google to sign in. Open it as a page, not a fetch."""
    user_service.require_sign_in_configured()
    return await oauth.google.authorize_redirect(
        request, settings.google_redirect_uri, prompt="select_account"
    )


@router.get(
    "/google/callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={
        400: {"description": "Google refused, or the state or ID token is invalid"},
        403: {"description": "Google hasn't verified the account's email"},
        503: {"description": "Google sign-in isn't configured on the server"},
    },
)
async def google_callback(request: Request, session: SessionDep) -> RedirectResponse:
    """Where Google sends the browser back. Checks the state and Google's ID
    token, finds or creates the user, starts the session and redirects to the
    frontend."""
    user_service.require_sign_in_configured()
    try:
        token = await oauth.google.authorize_access_token(
            request, claims_options={"iss": {"values": _GOOGLE_ISSUERS}}
        )
    except AuthlibBaseError as exc:  # bad or missing state, or Google said no
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Google sign-in failed: {exc.error}"
        ) from exc
    except JoseError as exc:  # the ID token's signature or claims are wrong
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Google sign-in failed: invalid ID token"
        ) from exc

    claims = token.get("userinfo")
    if claims is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Google sign-in failed: no ID token"
        )

    user = await user_service.sign_in(
        session,
        google_id=claims.get("sub"),
        email=claims.get("email"),
        email_verified=claims.get("email_verified") in (True, "true"),
        name=claims.get("name"),
    )
    # Start a fresh session: drops the flow's leftover state and anything a
    # previous session held, so a pre-login cookie never becomes a signed-in one.
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(settings.frontend_url, status.HTTP_302_FOUND)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    """End the session. Signing out when not signed in is not an error."""
    request.session.clear()


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"description": "Not signed in, or the session has expired"}},
)
async def me(user: CurrentUserDep, session: SessionDep) -> MeResponse:
    """The signed-in user and the hotels they work for."""
    hotels = await hotel_service.list_hotels_for_user(session, user.id)
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        hotels=[HotelResponse.model_validate(hotel) for hotel in hotels],
    )
