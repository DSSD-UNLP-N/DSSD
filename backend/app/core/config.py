from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_name: str = "RescueSync"
    bonita_base_url: str = "http://localhost:8080/bonita"
    bonita_username: str = "walter.bates"
    bonita_password: str = "bpm"
    bonita_process_name: str = "Gestion Integral de la Emergencia"
    bonita_process_version: str = "1.0"
    # Password compartida de los usuarios de prueba de la organización (ver entrega-2/ACME.xml).
    # bonita_username/password de arriba es el usuario técnico (walter.bates), para instanciar
    # y setear variables; estos son para completar tareas humanas (hay que ser miembro del actor).
    bonita_test_password: str = "bpm"
    # La primera llamada tras un rato sin uso tarda varios segundos (arranque en frío del motor).
    bonita_timeout_seconds: float = 10.0
    # Sistema Nacional (nacional/): catálogo de recursos y validación de ofertas.
    nacional_base_url: str = "http://localhost:8002"
    nacional_timeout_seconds: float = 60.0
    # Clave compartida con los conectores de Bonita (cabecera X-Api-Key en /api/bonita/*).
    bonita_api_key: str = "rescuesync-dev-key"
    database_url: str ="postgresql+psycopg://rescuesync:rescuesync@localhost:5432/rescuesync"
    jwt_secret: str = "dev-only-change-me"
    jwt_expiration_minutes: int = 60
    session_secret: str = "dev-only-change-me"
    ventana_provisoria_horas: int = 72
    # Muestra los usuarios de demo y su contraseña en el login. Solo para desarrollo/demo.
    show_demo_users: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
