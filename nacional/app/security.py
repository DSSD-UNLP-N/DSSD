import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Cuenta, RolCuenta

_ITERATIONS = 200_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate, digest)


def create_access_token(cuenta: Cuenta, secret: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": cuenta.username,
            "username": cuenta.username,
            "rol": cuenta.rol.value,
            "cuit": cuenta.ong.cuit if cuenta.ong else None,
            "iat": now,
            "exp": now + timedelta(minutes=expires_minutes),
        },
        secret,
        algorithm="HS256",
    )


def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Cuenta:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Token bearer requerido")
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub", "username", "rol"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Token inválido o vencido") from exc
    username = claims.get("username")
    if not isinstance(username, str) or not username or "cuit" not in claims:
        raise HTTPException(status_code=401, detail="Token inválido")
    cuenta = db.scalar(select(Cuenta).where(Cuenta.username == username))
    if (
        cuenta is None
        or claims.get("sub") != username
        or claims.get("rol") != cuenta.rol.value
        or claims.get("cuit") != (cuenta.ong.cuit if cuenta.ong else None)
    ):
        raise HTTPException(status_code=401, detail="Token inválido")
    return cuenta


def require_bonita(
    cuenta: Cuenta = Depends(get_current_account),
    settings: Settings = Depends(get_settings),
) -> Cuenta:
    if cuenta.rol is not RolCuenta.BONITA or cuenta.username != settings.bonita_service_username:
        raise HTTPException(status_code=403, detail="Se requiere la cuenta de servicio de Bonita")
    return cuenta


def require_ong_account(cuit: str, cuenta: Cuenta = Depends(get_current_account)) -> Cuenta:
    if cuenta.rol is not RolCuenta.ONG or cuenta.ong is None or cuenta.ong.cuit != cuit:
        raise HTTPException(status_code=403, detail="Solo podés modificar el inventario de tu propia ONG")
    return cuenta
