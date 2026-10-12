from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_url: str = (
        "postgresql+asyncpg://foresight:foresight@localhost:5432/foresight_db"
    )

    # External event sources
    predicthq_token: str = ""
    asknews_client_id: str = ""
    asknews_client_secret: str = ""
    # External APIs
    xrapidapi_key: str = ""  # RapidAPI key for AeroDataBox (flight arrivals)
    opensky_client_id: str = ""  # OpenSky API client (historical flights)
    opensky_client_secret: str = ""


settings = Settings()
