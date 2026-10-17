"""Cierre operativo: libera el inventario comprometido por una Adjudicacion ADJUDICADA.

Patron de bloqueo: igual que services/reservas.py —
  1. Bloquear la adjudicacion con with_for_update() + populate_existing (patron _cargar_bloqueada).
  2. Bloquear las filas de inventario ordenadas por id (patron liberar, anti-deadlock).
  3. Restar cantidad_comprometida, pasar estado a CERRADA y crear CierreOperativo + CierreItem.

Idempotencia: si el cierre ya existe para (ong_id, referencia) se devuelve sin tocar nada.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Adjudicacion,
    AdjudicacionItem,
    CierreItem,
    CierreOperativo,
    EstadoAdjudicacion,
    Inventario,
    Ong,
)


class CierreEnConflicto(RuntimeError):
    """409 — la adjudicacion no existe, no pertenece a la ONG o no esta en estado ADJUDICADA."""


class OngNoRegistrada(LookupError):
    """404 — CUIT desconocido."""


def cerrar(db: Session, cuit: str, referencia: str) -> tuple[int, bool]:
    """Cierra la adjudicacion identificada por (cuit, referencia).

    Devuelve (cierre_id, creado):
    - creado=True  → 201, primer cierre.
    - creado=False → 200, ya existia (idempotente: no resta de nuevo).

    Raises:
        OngNoRegistrada: si el CUIT no existe en el sistema.
        CierreEnConflicto: si la referencia no existe, no corresponde a esa ONG
                           o la adjudicacion no esta en estado ADJUDICADA.
    """
    ong = db.scalar(select(Ong).where(Ong.cuit == cuit))
    if ong is None:
        raise OngNoRegistrada(f"ONG con CUIT {cuit!r} no registrada")

    # Idempotencia: si el cierre ya existe, se devuelve sin restar nada.
    ya_id = db.scalar(
        select(CierreOperativo.id).where(
            CierreOperativo.ong_id == ong.id,
            CierreOperativo.referencia == referencia,
        )
    )
    if ya_id is not None:
        return ya_id, False

    # Cargar y bloquear la adjudicacion (patron _cargar_bloqueada de services/reservas.py).
    adj = db.scalar(
        select(Adjudicacion)
        .where(Adjudicacion.referencia_id == referencia, Adjudicacion.ong_id == ong.id)
        .with_for_update()
        .options(
            selectinload(Adjudicacion.items).selectinload(AdjudicacionItem.inventario)
        )
        .execution_options(populate_existing=True)
    )
    if adj is None:
        raise CierreEnConflicto(
            f"La referencia {referencia!r} no existe o no corresponde a esa ONG"
        )
    if adj.estado != EstadoAdjudicacion.ADJUDICADA:
        raise CierreEnConflicto(
            f"La referencia {referencia!r} esta en estado {adj.estado.value}; "
            "solo se puede cerrar en estado ADJUDICADA"
        )

    # Bloquear filas de inventario ordenadas por id (anti-deadlock; patron liberar de services/reservas.py).
    ids = sorted(i.inventario_id for i in adj.items)
    filas = (
        db.scalars(
            select(Inventario)
            .where(Inventario.id.in_(ids))
            .order_by(Inventario.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        if ids
        else []
    )
    por_id = {f.id: f for f in filas}

    # Restar el comprometido de cada item de la adjudicacion.
    for it in adj.items:
        por_id[it.inventario_id].cantidad_comprometida -= it.cantidad

    adj.estado = EstadoAdjudicacion.CERRADA

    # Registrar el cierre con un item por recurso liberado.
    cierre = CierreOperativo(
        ong_id=ong.id,
        referencia=referencia,
        informado_en=datetime.now(timezone.utc),
    )
    for it in adj.items:
        cierre.items.append(
            CierreItem(
                tipo_recurso_id=it.inventario.tipo_recurso_id,
                cantidad=it.cantidad,
            )
        )
    db.add(cierre)
    db.commit()
    return cierre.id, True
