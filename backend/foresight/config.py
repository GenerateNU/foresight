from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Root .env is the one docker-compose reads; backend/.env overrides it.
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


settings = Settings()
