"""Directiva 3: al vencer la ventana, Bonita le pide a la app el consolidado de ofertas.

Entregarlo pasa la emergencia a EN_EVALUACION: desde ahí lo ofrecido lo reserva la API Nacional
(`POST /evaluaciones`) y deja de contar en el tope local. Repetir el pedido devuelve lo mismo.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Emergencia, EstadoEmergencia, Oferta, OfertaItem
from app.schemas.evaluacion import Evaluacion
from app.services.emergencias import cerrar_ventanas_vencidas


class ConsolidadoError(RuntimeError):
    """La emergencia no está en un estado desde el que se pueda entregar el consolidado."""


def consolidar_ofertas(db: Session, emergencia_id: int) -> dict | None:
    """El consolidado del contrato (entrega-3/contratos.md, punto 2), o None si la emergencia no existe."""
    cerrar_ventanas_vencidas(db)
    e = db.scalar(
        select(Emergencia).where(Emergencia.id == emergencia_id).options(selectinload(Emergencia.lotes))
    )
    if e is None:
        return None
    if e.estado is EstadoEmergencia.CERRADA:
        e.estado = EstadoEmergencia.EN_EVALUACION
        db.commit()
    elif e.estado is not EstadoEmergencia.EN_EVALUACION:
        raise ConsolidadoError(
            f"La emergencia está en {e.estado.value}: solo se consolida una vez vencida la ventana de ofertas"
        )

    lotes = {l.id: l for l in e.lotes}
    ofertas = db.scalars(
        select(Oferta)
        .where(Oferta.emergencia_id == e.id)
        .options(selectinload(Oferta.items), selectinload(Oferta.ong))
        .order_by(Oferta.id)
    )
    consolidadas = []
    for o in ofertas:
        items = [
            {"lote_id": i.lote_id, "tipo_recurso": lotes[i.lote_id].tipo_recurso, "cantidad": i.cantidad}
            for i in _vigentes(o) if lotes[i.lote_id].tipo_recurso
        ]
        if items and o.ong.cuit:
            consolidadas.append({
                "cuit": o.ong.cuit, "ong": o.ong.nombre, "version": o.version_actual, "items": items,
            })
    return {
        "emergencia_id": e.id,
        "ronda": e.ronda,
        "gravedad": e.nivel_gravedad.value,
        "lotes": [
            {"lote_id": l.id, "tipo_recurso": l.tipo_recurso, "cantidad": l.cantidad, "tipo": l.tipo.value}
            for l in sorted(e.lotes, key=lambda l: l.id)
        ],
        "ofertas": consolidadas,
    }


def _vigentes(oferta: Oferta) -> list[OfertaItem]:
    return [i for i in oferta.items if i.version == oferta.version_actual]


def guardar_evaluacion(db: Session, emergencia_id: int, resultado: Evaluacion) -> bool:
    """Guarda lo que Bonita recibió de la API Nacional. False si la emergencia no existe.

    Solo vale mientras la emergencia espera la decisión (EN_EVALUACION) y para su ronda actual; repetir el
    mismo evento deja el mismo resultado."""
    e = db.get(Emergencia, emergencia_id)
    if e is None:
        return False
    if e.estado is not EstadoEmergencia.EN_EVALUACION:
        raise ConsolidadoError(f"La emergencia está en {e.estado.value}: ya no espera una evaluación")
    if resultado.emergencia_id != e.id or resultado.ronda != e.ronda:
        raise ConsolidadoError(
            f"La evaluación es de la emergencia {resultado.emergencia_id} ronda {resultado.ronda}, "
            f"y esta es la {e.id} ronda {e.ronda}"
        )
    e.evaluacion = resultado.model_dump_json()
    db.commit()
    return True
