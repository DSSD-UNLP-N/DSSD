from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Adjudicacion, AdjudicacionItem, Inventario
from app.schemas import AdjudicacionIn, AdjudicacionItemOut, AdjudicacionOut

router = APIRouter()


def _obtener_adjudicacion(db: Session, referencia_id: str) -> Adjudicacion | None:
    return db.scalar(
        select(Adjudicacion)
        .where(Adjudicacion.referencia_id == referencia_id)
        .options(selectinload(Adjudicacion.items))
    )


def _salida(adjudicacion: Adjudicacion) -> AdjudicacionOut:
    return AdjudicacionOut(
        id=adjudicacion.id,
        referencia_id=adjudicacion.referencia_id,
        ong_id=adjudicacion.ong_id,
        emergencia_id=adjudicacion.emergencia_id,
        fecha_creacion=adjudicacion.fecha_creacion,
        estado=adjudicacion.estado,
        items=[
            AdjudicacionItemOut(inventario_id=item.inventario_id, cantidad=item.cantidad)
            for item in adjudicacion.items
        ],
    )


@router.post("", response_model=AdjudicacionOut, status_code=201)
def adjudicar(
    body: AdjudicacionIn,
    response: Response,
    db: Session = Depends(get_db),
) -> AdjudicacionOut:
    """Compromete inventario bajo locks pesimistas e idempotencia por referencia."""
    cantidades: dict[int, int] = {}
    for item in body.items:
        if item.inventario_id in cantidades:
            raise HTTPException(
                status_code=400,
                detail="No se puede repetir un inventario en la misma adjudicación",
            )
        cantidades[item.inventario_id] = item.cantidad
    ids_ordenados = sorted(cantidades)

    try:
        with db.begin():
            existente = _obtener_adjudicacion(db, body.referencia_id)
            if existente is not None:
                response.status_code = 200
                return _salida(existente)

            filas = db.scalars(
                select(Inventario)
                .where(Inventario.id.in_(ids_ordenados))
                .order_by(Inventario.id.asc())
                .with_for_update()
            ).all()
            existente = _obtener_adjudicacion(db, body.referencia_id)
            if existente is not None:
                response.status_code = 200
                return _salida(existente)

            por_id = {fila.id: fila for fila in filas}
            if len(por_id) != len(ids_ordenados) or any(
                fila.ong_id != body.ong_id for fila in filas
            ):
                raise HTTPException(status_code=400, detail="Inventario inexistente")

            for inventario_id in ids_ordenados:
                fila = por_id[inventario_id]
                if cantidades[inventario_id] > fila.disponible:
                    raise HTTPException(
                        status_code=409,
                        detail="Stock insuficiente o ya adjudicado por otra transacción",
                    )

            adjudicacion = Adjudicacion(
                referencia_id=body.referencia_id,
                ong_id=body.ong_id,
                emergencia_id=body.emergencia_id,
                fecha_creacion=datetime.now(timezone.utc),
            )
            for inventario_id in ids_ordenados:
                fila = por_id[inventario_id]
                cantidad = cantidades[inventario_id]
                fila.cantidad_comprometida += cantidad
                adjudicacion.items.append(
                    AdjudicacionItem(inventario_id=fila.id, cantidad=cantidad)
                )
            db.add(adjudicacion)
            db.flush()
            db.refresh(adjudicacion)
            return _salida(adjudicacion)
    except IntegrityError:
        db.rollback()
        existente = _obtener_adjudicacion(db, body.referencia_id)
        if existente is not None:
            response.status_code = 200
            return _salida(existente)
        raise HTTPException(status_code=400, detail="No se pudo registrar la adjudicación") from None
