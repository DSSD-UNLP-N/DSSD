"""Alta de una ONG en los tres sistemas: Bonita (usuario + membresía), API Nacional (ONG + inventario) y la app.

El orden evita dejar cosas a medias: lo único que no se puede deshacer es el registro en la API Nacional, así que
lo local se crea al final y el usuario de Bonita se borra si algo falla después de crearlo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.integrations.bonita import BonitaClient, BonitaError
from app.integrations.nacional import NacionalClient, NacionalError
from app.models import Ong, Rol, Usuario

BONITA_GRUPO_ONG = "/rescuesync/ong"
BONITA_ROL_ONG = "representante_ong"

BONITA_CAIDO = "Bonita no responde; probá de nuevo en un momento."
NACIONAL_CAIDO = "El Sistema Nacional no responde; probá de nuevo en un momento."


class AltaOngError(Exception):
    """El alta no se pudo completar; `status` es el código HTTP que corresponde."""

    def __init__(self, mensaje: str, status: int = 409):
        super().__init__(mensaje)
        self.status = status


@dataclass
class DatosAlta:
    ong_nombre: str
    cuit: str
    nombre: str
    username: str
    password: str
    rubros: list[dict]


def normalizar_cuit(cuit: str) -> str:
    digitos = re.sub(r"\D", "", cuit)
    if len(digitos) != 11:
        raise AltaOngError("El CUIT debe tener 11 dígitos.", 422)
    return f"{digitos[:2]}-{digitos[2:10]}-{digitos[10]}"


def _borrar_usuario_bonita(bonita: BonitaClient, user_id: str | None) -> None:
    """Compensación: si falla, se ignora para que se informe el error original."""
    if user_id is None:
        return
    try:
        bonita.delete_user(user_id)
    except (BonitaError, requests.RequestException):
        pass


def _crear_en_bonita(settings: Settings, datos: DatosAlta) -> tuple[BonitaClient, str]:
    bonita = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    user_id: str | None = None
    try:
        bonita.login(settings.bonita_username, settings.bonita_password)
        if bonita.find_user_id(datos.username) is not None:
            raise AltaOngError("El usuario ya está registrado", 409)
        user_id = bonita.create_user(datos.username, settings.bonita_test_password, datos.nombre)
        bonita.add_membership(user_id, bonita.group_id(BONITA_GRUPO_ONG), bonita.role_id(BONITA_ROL_ONG))
    except (BonitaError, requests.RequestException) as exc:
        _borrar_usuario_bonita(bonita, user_id)
        raise AltaOngError(BONITA_CAIDO, 503) from exc
    return bonita, user_id


def alta_ong(db: Session, settings: Settings, nacional: NacionalClient, datos: DatosAlta) -> Usuario:
    cuit = normalizar_cuit(datos.cuit)

    existe = db.scalar(select(Ong.id).where(or_(Ong.nombre == datos.ong_nombre, Ong.cuit == cuit)))
    if existe is not None or db.scalar(select(Usuario.id).where(Usuario.username == datos.username)) is not None:
        raise AltaOngError("La ONG o el usuario ya está registrado", 409)

    bonita, user_id = _crear_en_bonita(settings, datos)

    try:
        token = nacional.registrar_ong(ong_nombre=datos.ong_nombre, cuit=cuit, nombre=datos.nombre,
                                       username=datos.username, password=datos.password)
    except NacionalError as exc:
        _borrar_usuario_bonita(bonita, user_id)
        if exc.status == 409:
            raise AltaOngError(str(exc), 409) from exc
        raise AltaOngError(NACIONAL_CAIDO, 503) from exc

    try:
        nacional.declarar_inventario(cuit, token, datos.rubros)
    except NacionalError as exc:
        _borrar_usuario_bonita(bonita, user_id)
        raise AltaOngError(
            "La ONG quedó registrada en el Sistema Nacional pero sin rubros: completalos desde Swagger con "
            f"PUT /ongs/{cuit}/inventario.", 502) from exc

    try:
        ong = Ong(nombre=datos.ong_nombre, cuit=cuit)
        usuario = Usuario(username=datos.username, password_hash=hash_password(datos.password),
                          nombre=datos.nombre, rol=Rol.ONG, ong=ong)
        db.add(usuario)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _borrar_usuario_bonita(bonita, user_id)
        raise AltaOngError("La ONG quedó registrada en el Sistema Nacional pero ya existe en la app.", 409) from exc
    return usuario
