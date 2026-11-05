from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Postgres schema all connections use. Tests set DB_SCHEMA=test.
    db_schema: str = "public"

    # Origins allowed to call the API from a browser (the React site). JSON list in the env var.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
