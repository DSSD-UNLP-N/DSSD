from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Cuenta, EstadoOng, Ong, RolCuenta
from app.schemas import LoginIn, RegisterOngIn, TokenOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(tags=["autenticación"])


def _token(cuenta: Cuenta, settings: Settings) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(cuenta, settings.jwt_secret, settings.jwt_expiration_minutes),
        user={
            "username": cuenta.username,
            "rol": cuenta.rol.value,
            "cuit": cuenta.ong.cuit if cuenta.ong else None,
        },
    )


@router.post("/login", response_model=TokenOut, summary="Iniciar sesión y emitir JWT")
def login(
    body: LoginIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    cuenta = db.scalar(select(Cuenta).where(Cuenta.username == body.username.strip()))
    if cuenta is None or not verify_password(body.password, cuenta.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return _token(cuenta, settings)


@router.post("/ongs", response_model=TokenOut, status_code=status.HTTP_201_CREATED,
             summary="Registrar una ONG y su cuenta")
def registrar_ong(
    body: RegisterOngIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if db.scalar(select(Cuenta.id).where(func.lower(Cuenta.username) == body.username.lower())):
        raise HTTPException(status_code=409, detail="El nombre de usuario ya está registrado")
    if db.scalar(select(Ong.id).where(func.lower(Ong.nombre) == body.ong_nombre.lower())):
        raise HTTPException(status_code=409, detail="La ONG ya está registrada")
    if db.scalar(select(Ong.id).where(Ong.cuit == body.cuit)):
        raise HTTPException(status_code=409, detail="El CUIT ya está registrado")

    try:
        ong = Ong(cuit=body.cuit, nombre=body.ong_nombre, estado=EstadoOng.HABILITADA)
        cuenta = Cuenta(
            username=body.username,
            password_hash=hash_password(body.password),
            rol=RolCuenta.ONG,
            ong=ong,
        )
        db.add(cuenta)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="La ONG o la cuenta ya están registradas") from exc
    db.refresh(cuenta)
    return _token(cuenta, settings)
