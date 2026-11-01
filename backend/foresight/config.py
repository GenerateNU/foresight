from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def to_asyncpg_url(url: str) -> str:
    """Normalize a libpq-style Postgres URL (e.g. from `neon env pull`) for asyncpg.

    asyncpg rejects libpq-only query params: `sslmode` becomes asyncpg's `ssl`,
    and `channel_binding` is dropped (asyncpg negotiates SCRAM itself).
    """
    if not url:
        return url
    parts = urlsplit(url)
    is_pg = parts.scheme.startswith("postgres")
    scheme = "postgresql+asyncpg" if is_pg else parts.scheme
    query = []
    for key, value in parse_qsl(parts.query):
        if key == "channel_binding":
            continue
        query.append(("ssl" if key == "sslmode" else key, value))
    return urlunsplit(parts._replace(scheme=scheme, query=urlencode(query)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Load root .env first (the one docker-compose reads), then backend/.env.
        # With a tuple, later files win, so a local backend/.env overrides root.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Foresight"
    debug: bool = False

    # Database
    # App traffic. On Neon this is the pooled (-pooler) connection string.
    database_url: str = (
        "postgresql+asyncpg://foresight:foresight@localhost:5432/foresight_db"
    )
    # Direct (non-pooled) connection for Alembic migrations. On Neon, PgBouncer
    # runs in transaction mode, so migrations must bypass it. Falls back to
    # database_url when unset (e.g. local Docker Postgres).
    database_url_unpooled: str = ""

    @property
    def async_database_url(self) -> str:
        return to_asyncpg_url(self.database_url)

    @property
    def async_migration_database_url(self) -> str:
        return to_asyncpg_url(self.database_url_unpooled or self.database_url)

    # External event sources
    predicthq_token: str = ""
    # External APIs
    xrapidapi_key: str = ""  # RapidAPI key for AeroDataBox (flight arrivals)
    opensky_client_id: str = ""  # OpenSky API client (historical flights)
    opensky_client_secret: str = ""

    # Sign-in
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match the redirect URI registered on the Google OAuth client exactly.
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Where sign-in returns to, and the only origin CORS allows. No path.
    frontend_url: str = "http://localhost:5173"
    # Signs the session cookie: `openssl rand -hex 32`.
    session_secret: str = ""
    # A session ends this long after the last request.
    session_max_age_seconds: int = 14 * 24 * 60 * 60
    # HTTPS-only cookie; false only for plain-http local dev.
    session_cookie_secure: bool = True
    # "none" if the frontend and API are on different sites (needs secure).
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @property
    def frontend_origin(self) -> str:
        return self.frontend_url.rstrip("/")

    @model_validator(mode="after")
    def _samesite_none_needs_secure(self) -> "Settings":
        # Browsers drop a SameSite=None cookie that isn't Secure.
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError(
                "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true"
            )
        return self


settings = Settings()
