"""App setup: routers, error handling, lifespan, and the API reference."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from scalar_fastapi import Theme, get_scalar_api_reference
from starlette.middleware.sessions import SessionMiddleware

from foresight import worker
from foresight.config import settings
from foresight.routes import (
    auth,
    city,
    event,
    feedback,
    health,
    hotel,
    ingest,
    job,
    pricing_model,
    weather,
)
from foresight.routes.access import SESSION_COOKIE, get_current_user
from foresight.routes.errors import register_error_handlers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Background jobs die with the process; anything left running is stale.
    await worker.fail_interrupted_jobs()
    yield


app = FastAPI(
    title=settings.app_name,
    description="AI revenue intelligence platform for boutique hotels",
    version="0.1.0",
    # Use Scalar for the API reference instead of the built-in Swagger UI.
    docs_url=None,
    lifespan=lifespan,
)

register_error_handlers(app)

# The session cookie
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or secrets.token_urlsafe(32),
    session_cookie=SESSION_COOKIE,
    max_age=settings.session_max_age_seconds,
    same_site=settings.session_cookie_samesite,
    https_only=settings.session_cookie_secure,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


login_required: dict[str, Any] = {
    "dependencies": [Depends(get_current_user)],
    "responses": {401: {"description": "Not signed in, or the session has expired"}},
}

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(city.router, **login_required)
app.include_router(hotel.router, **login_required)
app.include_router(feedback.router, **login_required)
app.include_router(weather.router, **login_required)
app.include_router(event.router, **login_required)
app.include_router(ingest.router, **login_required)
app.include_router(job.router, **login_required)
app.include_router(pricing_model.router, **login_required)


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
        theme=Theme.DEEP_SPACE,
    )
