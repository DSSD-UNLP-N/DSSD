from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

NACIONAL_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=NACIONAL_DIR / ".env", extra="ignore")

    app_name: str = "Sistema Nacional de Gestión de Recursos y Riesgos"
    database_url: str = f"sqlite:///{NACIONAL_DIR / 'nacional.db'}"

    @field_validator("database_url", mode="before")
    @classmethod
    def _driver_postgres(cls, url: str) -> str:
        # Render entrega postgres://; SQLAlchemy con psycopg 3 pide el driver explícito.
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url.removeprefix("postgres://")
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql://")
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
