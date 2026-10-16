"""T-11/T-12: ofertas de las ONGs, versionadas, con tope por inventario.

Cada envío es la oferta completa: una versión nueva con todos sus ítems; las anteriores no se
tocan (trazabilidad). Retirar un lote es enviar la oferta sin él; retirarla toda, enviarla vacía. Antes de guardar, lo que la ONG ofrece de cada recurso se suma con lo que
ya ofreció en sus otras convocatorias sin evaluar y se valida contra el inventario del Sistema
Nacional: no puede prometer más de lo que tiene, ni el mismo recurso dos veces.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.integrations.nacional import NacionalClient
from app.models import Emergencia, EstadoEmergencia, Oferta, OfertaItem, Ong
from app.schemas.api import OfertaItemIn


class OfertaError(RuntimeError):
    """La oferta no se puede guardar (ventana cerrada, lotes inválidos, no alcanza el inventario…)."""


# Hasta que Bonita pide el consolidado (EN_EVALUACION) la reserva no existe en la API Nacional:
# lo ofrecido en una convocatoria abierta, o vencida y sin evaluar, compromete el stock acá.
COMPROMETEN_STOCK = (EstadoEmergencia.CONVOCATORIA, EstadoEmergencia.CERRADA)


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
    db: Session, nacional: NacionalClient, *, emergencia: Emergencia, ong: Ong | None, items: list[OfertaItemIn]
) -> Oferta:
    """Guarda una versión nueva de la oferta de `ong` en `emergencia`.

    Lanza OfertaError si no corresponde, o NacionalError si el Sistema Nacional no responde:
    nunca se guarda una oferta sin validar."""
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

    # Serializa a la misma ONG (Postgres): dos envíos simultáneos no pueden pasar el tope a la vez.
    # SQLite ignora el bloqueo, y ahí no hace falta.
    db.execute(select(Ong.id).where(Ong.id == ong.id).with_for_update())

    oferta = db.scalar(
        select(Oferta)
        .where(Oferta.emergencia_id == emergencia.id, Oferta.ong_id == ong.id)
        .options(selectinload(Oferta.items))
    )
    if not items and (oferta is None or not _items_vigentes(oferta)):
        raise OfertaError("No tenés una oferta para retirar")
    _validar_tope(db, nacional, emergencia, ong, oferta, items, ahora)

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


def _items_vigentes(oferta: Oferta) -> list[OfertaItem]:
    return [i for i in oferta.items if i.version == oferta.version_actual]


def _validar_tope(
    db: Session, nacional: NacionalClient, emergencia: Emergencia, ong: Ong,
    oferta_actual: Oferta | None, items: list[OfertaItemIn], ahora: datetime,
) -> None:
    por_lote = {l.id: l for l in emergencia.lotes}
    # Lo que ofrece de cada recurso en esta versión y en la que reemplaza. Los lotes sin tipo
    # (anteriores al catálogo) no se validan.
    nuevos: Counter[str] = Counter()
    for item in items:
        if por_lote[item.lote_id].tipo_recurso:
            nuevos[por_lote[item.lote_id].tipo_recurso] += item.cantidad
    previos: Counter[str] = Counter()
    if oferta_actual is not None:
        for i in _items_vigentes(oferta_actual):
            if por_lote[i.lote_id].tipo_recurso:
                previos[por_lote[i.lote_id].tipo_recurso] += i.cantidad

    # Solo se controla lo que esta oferta aumenta: reducir o retirar nunca se rechaza (ni consulta a la API).
    a_validar = {t for t, n in nuevos.items() if n > previos[t]}
    if not a_validar:
        return
    if not ong.cuit:
        raise OfertaError("Tu ONG no tiene CUIT registrado; no se puede validar su inventario.")

    # Lo ya ofrecido en sus otras convocatorias sin evaluar también compromete el stock.
    total: Counter[str] = Counter({t: nuevos[t] for t in a_validar})
    otras = db.scalars(
        select(Oferta)
        .where(Oferta.ong_id == ong.id, Oferta.emergencia_id != emergencia.id)
        .options(selectinload(Oferta.items).selectinload(OfertaItem.lote), selectinload(Oferta.emergencia))
    )
    for otra in otras:
        if otra.emergencia.estado not in COMPROMETEN_STOCK:
            continue
        for i in _items_vigentes(otra):
            if i.lote.tipo_recurso in a_validar:
                total[i.lote.tipo_recurso] += i.cantidad

    resultado = nacional.validar(
        emergencia.nivel_gravedad.value,
        [{"cuit": ong.cuit, "tipo_recurso": t, "cantidad": n} for t, n in total.items()],
    )
    faltan = [
        f"{r['nombre_recurso']}: entre tus ofertas abiertas sumás {r['solicitado']} {r['unidad']} "
        f"y tenés {r['disponible']} disponibles"
        for r in resultado["resultados"] if not r["alcanza"]
    ]
    if faltan:
        raise OfertaError("No alcanza tu inventario. " + "; ".join(faltan) + ".")
