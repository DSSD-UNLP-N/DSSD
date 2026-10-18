"""Cierre operativo: la ONG informa que terminó una actividad y se liberan los recursos bloqueados."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import CierreItem, CierreOperativo, Ong
from app.schemas import CierreIn, CierreItemOut, CierreOut
from app.security import require_bonita
from app.services import cierres

router = APIRouter(tags=["cierre"], dependencies=[Depends(require_bonita)])


def _out(cierre: CierreOperativo) -> CierreOut:
    por_tipo = {f.tipo_recurso_id: f for f in cierre.ong.inventario}
    items = []
    for i in cierre.items:
        fila = por_tipo[i.tipo_recurso_id]
        items.append(
            CierreItemOut(
                tipo_recurso=i.tipo_recurso.codigo,
                nombre=i.tipo_recurso.nombre,
                unidad=i.tipo_recurso.unidad,
                cantidad_liberada=i.cantidad,
                cantidad_total=fila.cantidad_total,
                cantidad_comprometida=fila.cantidad_comprometida,
                disponible=fila.disponible,
            )
        )
    return CierreOut(
        id=cierre.id,
        cuit=cierre.ong.cuit,
        ong=cierre.ong.nombre,
        referencia=cierre.referencia,
        informado_en=cierre.informado_en,
        items=items,
    )


def _cargar_cierre(db: Session, cierre_id: int) -> CierreOperativo | None:
    return db.scalar(
        select(CierreOperativo)
        .where(CierreOperativo.id == cierre_id)
        .options(
            selectinload(CierreOperativo.ong).selectinload(Ong.inventario),
            selectinload(CierreOperativo.items).selectinload(CierreItem.tipo_recurso),
        )
    )


@router.post(
    "/cierres",
    response_model=CierreOut,
    status_code=201,
    summary="Informar el cierre de una actividad y liberar el stock comprometido",
)
def informar_cierre(body: CierreIn, response: Response, db: Session = Depends(get_db)):
    """Busca la Adjudicacion ADJUDICADA para esa referencia, resta su inventario comprometido,
    la pasa a CERRADA y registra el CierreOperativo.
    Idempotente: repetir con la misma referencia devuelve 200 con el cierre ya existente."""
    try:
        cierre_id, creado = cierres.cerrar(db, body.cuit, body.referencia)
    except cierres.OngNoRegistrada as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except cierres.CierreEnConflicto as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        # Carrera: otro request creo el cierre justo antes; rollback y devolver el existente.
        db.rollback()
        ong = db.scalar(select(Ong).where(Ong.cuit == body.cuit))
        cierre_id = (
            db.scalar(
                select(CierreOperativo.id).where(
                    CierreOperativo.ong_id == ong.id,
                    CierreOperativo.referencia == body.referencia,
                )
            )
            if ong is not None
            else None
        )
        if cierre_id is None:
            raise HTTPException(status_code=409, detail="Error al registrar el cierre")
        creado = False

    if not creado:
        response.status_code = 200

    cargado = _cargar_cierre(db, cierre_id)
    return _out(cargado)


@router.get("/cierres/{cierre_id}", response_model=CierreOut, summary="Ver un cierre ya informado")
def obtener_cierre(cierre_id: int, db: Session = Depends(get_db)):
    cierre = _cargar_cierre(db, cierre_id)
    if cierre is None:
        raise HTTPException(status_code=404, detail="Cierre no encontrado")
    return _out(cierre)


@router.get("/ongs/{cuit}/cierres", response_model=list[CierreOut], summary="Cierres informados por una ONG")
def cierres_de_la_ong(cuit: str, db: Session = Depends(get_db)):
    ong = db.scalar(select(Ong).where(Ong.cuit == cuit))
    if ong is None:
        raise HTTPException(status_code=404, detail="ONG no registrada")
    cierre_list = db.scalars(
        select(CierreOperativo)
        .where(CierreOperativo.ong_id == ong.id)
        .order_by(CierreOperativo.id)
        .options(
            selectinload(CierreOperativo.ong).selectinload(Ong.inventario),
            selectinload(CierreOperativo.items).selectinload(CierreItem.tipo_recurso),
        )
    )
    return [_out(c) for c in cierre_list]
