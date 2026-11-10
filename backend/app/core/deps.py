import hmac
import logging

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import get_db
from app.models import Rol, Usuario

log = logging.getLogger(__name__)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Usuario | None:
    uid = request.session.get("uid")
    if uid is None:
        return None
    user = db.get(Usuario, uid)
    if user is None:  # usuario borrado con la sesión viva
        request.session.clear()
    return user


def require_role(*roles: Rol):
    """Dependencia de ruta: 401 si no hay sesión, 403 si el rol no está permitido.
    Sin roles, solo exige estar logueado. Uso: `user = Depends(require_role(Rol.COORDINADOR))`."""

    def dep(user: Usuario | None = Depends(get_current_user)) -> Usuario:
        if user is None:
            raise HTTPException(status_code=401, detail="Iniciá sesión")
        if roles and user.rol not in roles:
            raise HTTPException(status_code=403, detail="Tu perfil no tiene acceso a esta sección")
        return user

    return dep


def get_bonita_lectura(settings: Settings = Depends(get_settings)):
    """Devuelve un BonitaClient ya logueado con la cuenta técnica, o None si Bonita no responde.

    La función de servicio `reporte()` maneja el caso None devolviendo tiempos.disponible=False,
    por lo que el endpoint siempre responde 200 incluso con Bonita caído.
    """
    import requests as req

    from app.integrations.bonita import BonitaClient, BonitaError

    try:
        client = BonitaClient(settings.bonita_base_url, timeout=settings.bonita_timeout_seconds)
        client.login(settings.bonita_username, settings.bonita_password)
        return client
    except (req.RequestException, BonitaError) as exc:
        log.warning("Bonita no disponible en get_bonita_lectura: %s", exc)
        return None


def require_bonita_key(
    x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> None:
    """Los endpoints /api/bonita/* los llama el motor de Bonita, no una persona: no hay sesión,
    solo la clave compartida. 401 si falta o no coincide."""
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), settings.bonita_api_key.encode()):
        raise HTTPException(status_code=401, detail="Clave de Bonita inválida")
