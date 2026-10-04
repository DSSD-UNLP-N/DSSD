from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

NACIONAL_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=NACIONAL_DIR / ".env", extra="ignore")

    app_name: str = "Sistema Nacional de Gestión de Recursos y Riesgos"
    database_url: str = f"sqlite:///{NACIONAL_DIR / 'nacional.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
