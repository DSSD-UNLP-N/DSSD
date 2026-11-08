"""Consorcios entre ONGs: reglas de formación (crear, invitar, responder, salir, disolver).

El consorcio pertenece a la emergencia, no a la ronda: solo se edita mientras la ventana de ofertas está abierta
(la misma regla que `ofertas._esta_abierta`), también en la segunda ronda. Una invitación sin responder cuando la
ventana cierra queda vencida: no cuenta ni se puede aceptar. Las filas de membresía no se borran (trazabilidad); volver
a invitar a una ONG que rechazó o salió crea una fila nueva.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Consorcio, ConsorcioMiembro, Emergencia, EstadoMiembro, Notificacion, Ong,
)
from app.services.ofertas import _esta_abierta

NOMBRE_MIN, NOMBRE_MAX = 2, 80
NOMBRE_REPETIDO = "Ya hay un consorcio con ese nombre en esta emergencia."


class ConsorcioError(RuntimeError):
    """La operación no corresponde (ventana cerrada, regla de membresía, permiso, nombre inválido)."""

    def __init__(self, mensaje: str, status: int = 409):
        super().__init__(mensaje)
        self.status = status


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _emergencia(db: Session, c: Consorcio) -> Emergencia:
    return db.get(Emergencia, c.emergencia_id)


def _exigir_abierta(e: Emergencia, ahora: datetime) -> None:
    if not _esta_abierta(e, ahora):
        raise ConsorcioError("La ventana de ofertas no está abierta: los consorcios ya no se pueden modificar.")


def _exigir_vivo(c: Consorcio) -> None:
    if c.disuelto_en is not None:
        raise ConsorcioError("El consorcio está disuelto.")


def _fila_activa(c: Consorcio, ong_id: int, estados: tuple[EstadoMiembro, ...]) -> ConsorcioMiembro | None:
    return next((m for m in c.miembros if m.ong_id == ong_id and m.estado in estados), None)


def consorcio_de(db: Session, emergencia_id: int, ong_id: int) -> Consorcio | None:
    """El consorcio no disuelto de la emergencia donde la ONG está INVITADA (con la ventana abierta) o ACEPTADA."""
    emergencia = db.get(Emergencia, emergencia_id)
    abierta = emergencia is not None and _esta_abierta(emergencia, _ahora())
    filas = db.scalars(
        select(ConsorcioMiembro)
        .join(Consorcio)
        .where(
            Consorcio.emergencia_id == emergencia_id,
            Consorcio.disuelto_en.is_(None),
            ConsorcioMiembro.ong_id == ong_id,
            ConsorcioMiembro.estado.in_([EstadoMiembro.INVITADA, EstadoMiembro.ACEPTADA]),
        )
        .options(selectinload(ConsorcioMiembro.consorcio))
    )
    for m in filas:
        if m.estado is EstadoMiembro.ACEPTADA or abierta:
            return m.consorcio
    return None


def crear(db: Session, *, emergencia: Emergencia, ong: Ong, nombre: str) -> Consorcio:
    ahora = _ahora()
    _exigir_abierta(emergencia, ahora)
    nombre = (nombre or "").strip()
    if not NOMBRE_MIN <= len(nombre) <= NOMBRE_MAX:
        raise ConsorcioError(f"El nombre del consorcio debe tener entre {NOMBRE_MIN} y {NOMBRE_MAX} caracteres.", 422)
    # También cuenta el nombre de un consorcio disuelto: la tabla exige nombres únicos por emergencia.
    if db.scalar(select(Consorcio.id).where(Consorcio.emergencia_id == emergencia.id, Consorcio.nombre == nombre)):
        raise ConsorcioError(NOMBRE_REPETIDO)
    if consorcio_de(db, emergencia.id, ong.id) is not None:
        raise ConsorcioError("Tu ONG ya está en un consorcio de esta emergencia.")
    c = Consorcio(emergencia_id=emergencia.id, nombre=nombre, ong_lider_id=ong.id, creado_en=ahora)
    c.miembros.append(ConsorcioMiembro(
        ong_id=ong.id, estado=EstadoMiembro.ACEPTADA, invitado_por_ong_id=ong.id, invitado_en=ahora,
        respondido_en=ahora))
    db.add(c)
    db.commit()
    return c


def invitar(db: Session, *, consorcio: Consorcio, lider: Ong, invitada: Ong) -> ConsorcioMiembro:
    if consorcio.ong_lider_id != lider.id:
        raise ConsorcioError("Solo la ONG líder puede invitar.", 403)
    ahora = _ahora()
    emergencia = _emergencia(db, consorcio)
    _exigir_abierta(emergencia, ahora)
    _exigir_vivo(consorcio)
    if invitada.id == lider.id:
        raise ConsorcioError("No podés invitar a tu propia ONG.")
    if consorcio_de(db, emergencia.id, invitada.id) is not None:
        raise ConsorcioError(f"{invitada.nombre} ya está en un consorcio de esta emergencia.")
    m = ConsorcioMiembro(
        ong_id=invitada.id, estado=EstadoMiembro.INVITADA, invitado_por_ong_id=lider.id, invitado_en=ahora)
    consorcio.miembros.append(m)
    db.add(Notificacion(
        ong_id=invitada.id, emergencia_id=emergencia.id,
        texto=f"{lider.nombre} te invitó al consorcio \"{consorcio.nombre}\" en la emergencia #{emergencia.id}. "
              "Podés aceptar o rechazar desde la convocatoria."[:300]))
    db.commit()
    return m


def responder(db: Session, *, consorcio: Consorcio, ong: Ong, acepta: bool) -> ConsorcioMiembro:
    fila = _fila_activa(consorcio, ong.id, (EstadoMiembro.INVITADA,))
    if fila is None:
        raise ConsorcioError("Tu ONG no tiene una invitación pendiente en este consorcio.", 403)
    ahora = _ahora()
    _exigir_abierta(_emergencia(db, consorcio), ahora)
    _exigir_vivo(consorcio)
    if acepta and consorcio_de(db, consorcio.emergencia_id, ong.id) not in (None, consorcio):
        raise ConsorcioError("Tu ONG ya está en otro consorcio de esta emergencia.")
    fila.estado = EstadoMiembro.ACEPTADA if acepta else EstadoMiembro.RECHAZADA
    fila.respondido_en = ahora
    db.commit()
    return fila


def salir(db: Session, *, consorcio: Consorcio, ong: Ong) -> None:
    if consorcio.ong_lider_id == ong.id:
        raise ConsorcioError("La ONG líder no puede salir: tiene que disolver el consorcio.")
    _exigir_abierta(_emergencia(db, consorcio), _ahora())
    _exigir_vivo(consorcio)
    fila = _fila_activa(consorcio, ong.id, (EstadoMiembro.ACEPTADA,))
    if fila is None:
        raise ConsorcioError("Tu ONG no es miembro de este consorcio.")
    fila.estado = EstadoMiembro.SALIO
    fila.salio_en = _ahora()
    db.commit()


def disolver(db: Session, *, consorcio: Consorcio, lider: Ong) -> None:
    if consorcio.ong_lider_id != lider.id:
        raise ConsorcioError("Solo la ONG líder puede disolver el consorcio.", 403)
    _exigir_abierta(_emergencia(db, consorcio), _ahora())
    _exigir_vivo(consorcio)
    consorcio.disuelto_en = _ahora()
    db.commit()


def miembros_aceptados(c: Consorcio) -> list[ConsorcioMiembro]:
    return [m for m in c.miembros if m.estado is EstadoMiembro.ACEPTADA]


def es_valido(c: Consorcio) -> bool:
    """Un consorcio cuenta (para el Municipio y el dashboard) con 2 o más miembros aceptados y sin disolver."""
    return c.disuelto_en is None and len(miembros_aceptados(c)) >= 2


def consorcios_validos(db: Session, emergencia_id: int) -> list[Consorcio]:
    todos = db.scalars(
        select(Consorcio)
        .where(Consorcio.emergencia_id == emergencia_id, Consorcio.disuelto_en.is_(None))
        .order_by(Consorcio.id)
        .options(selectinload(Consorcio.miembros))
    )
    return [c for c in todos if es_valido(c)]
