import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Postgres schema all connections use. Tests set DB_SCHEMA=test.
    db_schema: str = "public"

    # Origins allowed to call the API from a browser (the React site). The env var can be a JSON
    # list, a comma-separated list or a single URL; an empty value falls back to the local defaults.
    cors_origins: Annotated[list[str], NoDecode] = DEFAULT_CORS_ORIGINS

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                v = json.loads(v)
            else:
                v = v.split(",")
        origins = [o.strip().strip("\"'").rstrip("/") for o in v]
        return [o for o in origins if o] or DEFAULT_CORS_ORIGINS

    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()
