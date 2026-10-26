from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    asknews_client_id: str = ""
    asknews_client_secret: str = ""
    # External APIs
    xrapidapi_key: str = ""  # RapidAPI key for AeroDataBox (flight arrivals)
    opensky_client_id: str = ""  # OpenSky API client (historical flights)
    opensky_client_secret: str = ""


settings = Settings()
