"""T-11/T-12: ofertas de las ONGs, versionadas.

Cada envío es la oferta completa: una versión nueva con todos sus ítems; las anteriores no se
tocan (trazabilidad). Retirar un lote es enviar la oferta sin él; retirarla toda, enviarla vacía.
La app no valida contra el Sistema Nacional: lo hace Bonita cuando vence la ventana (la app nunca
llama a la API Nacional; ver pautas de la cátedra).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Emergencia, EstadoEmergencia, Oferta, OfertaItem, Ong
from app.schemas.api import OfertaItemIn
from app.services import ServicioError


class OfertaError(ServicioError):
    """La oferta no se puede guardar (ventana cerrada, lotes inválidos…)."""


def _esta_abierta(e: Emergencia, ahora: datetime) -> bool:
    if e.estado is not EstadoEmergencia.CONVOCATORIA:
        return False
    fin = e.ventana_ofertas_fin
    return fin is None or fin.replace(tzinfo=fin.tzinfo or timezone.utc) > ahora


def _verificar_abierta(e: Emergencia, ahora: datetime) -> None:
    if e.estado is EstadoEmergencia.REGISTRADA:
        raise OfertaError("La convocatoria no está abierta")
    if e.estado is not EstadoEmergencia.CONVOCATORIA:
        raise OfertaError("La ventana de ofertas ya cerró")
    if not _esta_abierta(e, ahora):
        raise OfertaError("La ventana de ofertas ya cerró")


def publicar_oferta(
    db: Session, *, emergencia: Emergencia, ong: Ong | None, items: list[OfertaItemIn]
) -> Oferta:
    """Guarda una versión nueva de la oferta de `ong` en `emergencia`. Lanza OfertaError si no corresponde."""
    ahora = datetime.now(timezone.utc)
    _verificar_abierta(emergencia, ahora)
    if ong is None:
        raise OfertaError("Tu usuario no tiene ONG asignada")

    por_lote = {l.id: l for l in emergencia.lotes}
    pedidos = [item.lote_id for item in items]
    if len(set(pedidos)) != len(pedidos):
        raise OfertaError("Hay lotes repetidos en la oferta")
    for lote_id in pedidos:
        if lote_id not in por_lote:
            raise OfertaError(f"Lote {lote_id} inválido")

    oferta = db.scalar(
        select(Oferta)
        .where(Oferta.emergencia_id == emergencia.id, Oferta.ong_id == ong.id)
        .options(selectinload(Oferta.items))
    )
    if not items and (oferta is None or not oferta.items_vigentes):
        raise OfertaError("No tenés una oferta para retirar")

    if oferta is None:
        oferta = Oferta(emergencia_id=emergencia.id, ong_id=ong.id, version_actual=1)
        db.add(oferta)
        db.flush()
    else:
        oferta.version_actual += 1
    for item in items:
        db.add(OfertaItem(oferta_id=oferta.id, version=oferta.version_actual, lote_id=item.lote_id,
                          recurso=item.recurso, cantidad=item.cantidad))
    db.commit()
    db.refresh(oferta)
    return oferta

