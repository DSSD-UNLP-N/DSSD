from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

NACIONAL_DIR = Path(__file__).resolve().parents[1]

# Valores de ejemplo que están en el repositorio: en la nube (Postgres) no pueden quedar, porque con el secreto a la
# vista cualquiera firma un token válido.
SECRETOS_DE_EJEMPLO = {"dev-only-change-me", "change-me", "change-me-app"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=NACIONAL_DIR / ".env", extra="ignore")

    app_name: str = "Sistema Nacional de Gestión de Recursos y Riesgos"
    database_url: str = f"sqlite:///{NACIONAL_DIR / 'nacional.db'}"
    jwt_secret: str = "dev-only-change-me"
    jwt_expiration_minutes: int = 60
    bonita_service_username: str = "bonita-service"
    bonita_service_password: str = "change-me"
    app_service_username: str = "app-service"
    app_service_password: str = "change-me-app"

    @model_validator(mode="after")
    def _sin_secretos_de_ejemplo_en_la_nube(self):
        if self.database_url.startswith("sqlite"):
            return self
        usados = [
            nombre for nombre, valor in (
                ("JWT_SECRET", self.jwt_secret),
                ("BONITA_SERVICE_PASSWORD", self.bonita_service_password),
                ("APP_SERVICE_PASSWORD", self.app_service_password),
            ) if valor in SECRETOS_DE_EJEMPLO
        ]
        if usados:
            raise ValueError("Con Postgres hay que definir valores propios para: " + ", ".join(usados))
        return self

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
