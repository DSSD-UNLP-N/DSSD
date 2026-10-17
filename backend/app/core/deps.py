from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import get_token_claims
import hmac

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import get_db
from app.models import Rol, Usuario

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Usuario | None:
    if credentials is None:
        return None
    claims = get_token_claims(credentials.credentials, settings.jwt_secret)
    if claims is None:
        return None
    username = claims.get("username")
    if isinstance(username, str):
        user = db.scalar(select(Usuario).where(Usuario.username == username))
        if user is None or claims.get("rol") != user.rol.value:
            return None
        user_cuit = user.ong.cuit if user.ong else None
        if claims.get("cuit") != user_cuit:
            return None
        return user

    user_id = claims.get("sub")
    return db.get(Usuario, int(user_id)) if isinstance(user_id, str) and user_id.isdecimal() else None


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


def require_bonita_key(
    x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> None:
    """Los endpoints /api/bonita/* los llama el motor de Bonita, no una persona: no hay sesión,
    solo la clave compartida. 401 si falta o no coincide."""
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), settings.bonita_api_key.encode()):
        raise HTTPException(status_code=401, detail="Clave de Bonita inválida")
