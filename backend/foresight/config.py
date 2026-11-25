from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def to_asyncpg_url(url: str) -> str:
    """Normalizes a libpq-style Postgres URL, e.g. from `neon env pull`, for asyncpg.

    asyncpg rejects libpq-only query params: `sslmode` becomes asyncpg's `ssl`,
    and `channel_binding` is dropped, since asyncpg negotiates SCRAM itself.

    Args:
        url (str): The URL; empty stays empty.

    Returns:
        str: The URL with the asyncpg driver and params.
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
    """The app's settings, from the environment, `../.env` and `.env`.

    The root `.env` (the one docker-compose reads) loads first, then
    `backend/.env`, which wins.

    Attributes:
        app_name (str): Shown in /docs.
        debug (bool): Logs every SQL statement.
        database_url (str): App traffic; on Neon, the pooled (-pooler) URL.
        database_url_unpooled (str): A direct connection for migrations,
            which on Neon must bypass PgBouncer's transaction mode; empty
            falls back to `database_url`.
        predicthq_token (str): PredictHQ's API token.
        upload_max_files (int): Most files in one upload. Parsed files wait
            in memory until their job runs.
        upload_max_file_mb (int): Largest file in an upload.
        scheduler_enabled (bool): Runs each hotel's routine jobs when due.
            Off locally, so a dev server doesn't call paid APIs on its own.
        scheduled_training (bool): Also retrains daily. Training runs in the
            web process, so only on a plan with the memory for it.
        schedule_hour (int): Hour of the day, 0-23 in each hotel's time, the
            routine jobs run. A missed hour is caught up at the next check.
        google_client_id (str): The Google OAuth client.
        google_client_secret (str): The Google OAuth client's secret.
        google_redirect_uri (str): Must match the redirect URI registered on
            the Google OAuth client exactly.
        frontend_url (str): Where sign-in returns to, and the only origin
            CORS allows. No path.
        session_secret (str): Signs the session cookie;
            `openssl rand -hex 32`.
        session_max_age_seconds (int): A session ends this long after the
            last request.
        session_cookie_secure (bool): HTTPS-only cookie; false only for
            plain-http local dev.
        session_cookie_samesite (Literal["lax", "strict", "none"]): "none"
            if the frontend and API are on different sites; needs secure.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Foresight"
    debug: bool = False

    database_url: str = (
        "postgresql+asyncpg://foresight:foresight@localhost:5432/foresight_db"
    )
    database_url_unpooled: str = ""

    predicthq_token: str = ""

    upload_max_files: int = 10
    upload_max_file_mb: int = 50

    scheduler_enabled: bool = False
    scheduled_training: bool = False
    schedule_hour: int = Field(default=3, ge=0, le=23)

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    frontend_url: str = "http://localhost:5173"
    session_secret: str = ""
    session_max_age_seconds: int = 14 * 24 * 60 * 60
    session_cookie_secure: bool = True
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @property
    def async_database_url(self) -> str:
        """The app's database URL, for asyncpg.

        Returns:
            str: The URL.
        """
        return to_asyncpg_url(self.database_url)

    @property
    def async_migration_database_url(self) -> str:
        """The migrations' database URL, for asyncpg.

        Returns:
            str: The unpooled URL, else the app's.
        """
        return to_asyncpg_url(self.database_url_unpooled or self.database_url)

    @property
    def frontend_origin(self) -> str:
        """The frontend's origin, for CORS.

        Returns:
            str: `frontend_url` without a trailing slash.
        """
        return self.frontend_url.rstrip("/")

    @model_validator(mode="after")
    def _samesite_none_needs_secure(self) -> "Settings":
        """Checks a SameSite=None cookie is Secure; browsers drop it otherwise.

        Returns:
            Settings: The settings.

        Raises:
            ValueError: SameSite is none but the cookie isn't secure.
        """
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError(
                "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true"
            )
        return self


settings = Settings()
