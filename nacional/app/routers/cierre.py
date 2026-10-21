"""Cierre operativo: terminó la actividad de una adjudicación y se libera exactamente lo que tenía comprometido."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import CierreItem, CierreOperativo, Ong
from app.routers.reservas import _ERRORES, _http
from app.schemas import CierreIn, CierreItemOut, CierreLoteIn, CierreOut, CuitPath
from app.security import require_servicio
from app.services import reservas

router = APIRouter(tags=["cierre"], dependencies=[Depends(require_servicio)])


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


@router.post("/cierres", response_model=CierreOut, status_code=201,
             summary="Cerrar una adjudicación y liberar lo que tenía comprometido")
def informar_cierre(body: CierreIn, response: Response, db: Session = Depends(get_db)):
    """Fin de la actividad (servicio 5). Exige que la `referencia` esté `ADJUDICADA`: resta del inventario
    exactamente lo que esa referencia tenía comprometido y la pasa a `CERRADA`. No se indican ítems.

    `201` con el cierre. Repetirlo responde `200` con el mismo cierre, sin restar de nuevo. `404` si la ONG o la
    referencia no existen (o la referencia es de otra ONG); `409` si la referencia no está `ADJUDICADA`."""
    try:
        try:
            cierre, nuevo = reservas.cerrar(db, body.cuit, body.referencia)
        except IntegrityError:
            # Dos cierres iguales a la vez (reintento de Bonita): el otro ganó; esta vez encuentra el cierre hecho.
            db.rollback()
            cierre, nuevo = reservas.cerrar(db, body.cuit, body.referencia)
    except _ERRORES as exc:
        raise _http(exc) from exc
    if not nuevo:
        response.status_code = 200
    return _out(_cargar_cierre(db, cierre.id))


@router.post("/cierres/lote", response_model=list[CierreOut],
             summary="Cerrar varias adjudicaciones de una emergencia en una sola llamada")
def informar_cierres(body: CierreLoteIn, db: Session = Depends(get_db)):
    """Lo que Bonita manda al validarse el cierre bilateral: un `{cuit, referencia}` por cada ONG adjudicada, y un
    solo pedido en vez de uno por ONG. Valida todo antes de cambiar nada (`404` si una ONG o referencia no existe,
    `409` si alguna no está `ADJUDICADA`, `400` si repite una referencia) y es idempotente: repetir la llamada
    completa devuelve los mismos cierres sin restar de nuevo. Cada cierre se comporta como en `POST /cierres`."""
    pedidos = [(c.cuit, c.referencia) for c in body.cierres]
    try:
        try:
            cerrados = reservas.cerrar_varias(db, pedidos)
        except IntegrityError:
            db.rollback()
            cerrados = reservas.cerrar_varias(db, pedidos)
    except _ERRORES as exc:
        raise _http(exc) from exc
    return [_out(_cargar_cierre(db, cierre.id)) for cierre, _ in cerrados]


@router.get("/cierres/{cierre_id}", response_model=CierreOut, summary="Ver un cierre ya informado")
def obtener_cierre(cierre_id: int, db: Session = Depends(get_db)):
    cierre = _cargar_cierre(db, cierre_id)
    if cierre is None:
        raise HTTPException(status_code=404, detail="Cierre no encontrado")
    return _out(cierre)


@router.get("/ongs/{cuit}/cierres", response_model=list[CierreOut], summary="Cierres informados por una ONG")
def cierres_de_la_ong(cuit: CuitPath, db: Session = Depends(get_db)):
    ong = db.scalar(select(Ong).where(Ong.cuit == cuit))
    if ong is None:
        raise HTTPException(status_code=404, detail="ONG no registrada")
    cierres = db.scalars(
        select(CierreOperativo)
        .where(CierreOperativo.ong_id == ong.id)
        .order_by(CierreOperativo.id)
        .options(
            selectinload(CierreOperativo.ong).selectinload(Ong.inventario),
            selectinload(CierreOperativo.items).selectinload(CierreItem.tipo_recurso),
        )
    )
    return [_out(c) for c in cierres]
