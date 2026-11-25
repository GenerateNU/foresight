from authlib.common.errors import AuthlibBaseError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import Field

from foresight.config import settings
from foresight.routes.access import CurrentUserDep
from foresight.routes.helpers import ResponseSchema, SessionDep
from foresight.routes.hotel import HotelResponse
from foresight.services.hotels import hotel as hotel_service
from foresight.services.users import user as user_service

router = APIRouter(prefix="/auth", tags=["Auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)

_GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


#          ╭──────────────────────────────────────────────────────────╮
#          │                         Schemas                          │
#          ╰──────────────────────────────────────────────────────────╯


class MeResponse(ResponseSchema):
    """The signed-in user and the hotels they work for."""

    id: int = Field(description="The user's id")
    email: str = Field(description="The email Google last reported for the account")
    name: str | None = Field(description="Their name on Google; null if it has none")
    hotels: list[HotelResponse] = Field(
        description="The hotels they work for; empty until an operator links one"
    )


#          ╭──────────────────────────────────────────────────────────╮
#          │                        Endpoints                         │
#          ╰──────────────────────────────────────────────────────────╯


@router.get(
    "/google/login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={503: {"description": "Google sign-in isn't configured on the server"}},
)
async def google_login(request: Request) -> RedirectResponse:
    """Send the browser to Google to sign in. Open it as a page, not a fetch.

    Google's authorization-code flow runs through Authlib, which keeps the
    flow's state and nonce in the signed session cookie. The OAuth client
    lives in routes because it reads and writes the HTTP session; the service
    only gets plain values.

    \f
    Args:
        request (Request): The request, with its session.

    Returns:
        RedirectResponse: To Google.

    Raises:
        NotConfiguredError: Google sign-in isn't configured.
    """
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
    """Where Google sends the browser back after sign-in.

    Checks the state and Google's ID token, finds or creates the user, starts
    the session and redirects to the frontend.

    Google documents two spellings of its issuer, and both are accepted;
    Authlib alone would accept only the one in its discovery document. The
    session is cleared before the user is stored, dropping the flow's state
    and anything a previous session held, so a pre-login cookie never becomes
    a signed-in one.

    \f
    Args:
        request (Request): The request, with its session.
        session (SessionDep): The database session.

    Returns:
        RedirectResponse: To the frontend.

    Raises:
        HTTPException: 400 if Google refused, or the state or ID token is
            invalid.
        ForbiddenError: Google hasn't verified the account's email.
        NotConfiguredError: Google sign-in isn't configured.
    """
    user_service.require_sign_in_configured()
    try:
        token = await oauth.google.authorize_access_token(
            request, claims_options={"iss": {"values": _GOOGLE_ISSUERS}}
        )
    except AuthlibBaseError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Google sign-in failed: {exc.error}"
        ) from exc
    except JoseError as exc:
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
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(settings.frontend_url, status.HTTP_302_FOUND)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    """End the session. Signing out when not signed in is not an error.

    \f
    Args:
        request (Request): The request, with its session.
    """
    request.session.clear()


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"description": "Not signed in, or the session has expired"}},
)
async def me(user: CurrentUserDep, session: SessionDep) -> MeResponse:
    """The signed-in user and the hotels they work for.

    \f
    Args:
        user (CurrentUserDep): The signed-in user.
        session (SessionDep): The database session.

    Returns:
        MeResponse: The user and their hotels.
    """
    hotels = await hotel_service.list_hotels_for_user(session, user.id)
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        hotels=[HotelResponse.model_validate(hotel) for hotel in hotels],
    )
