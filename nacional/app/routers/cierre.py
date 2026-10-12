"""Cierre operativo: la ONG informa que terminó una actividad y se liberan los recursos bloqueados."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import CierreItem, CierreOperativo, Inventario, Ong, TipoRecurso
from app.schemas import CierreIn, CierreItemOut, CierreOut

router = APIRouter(tags=["cierre"])


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


@router.post("/cierres", response_model=CierreOut, status_code=201, summary="Informar el cierre de una actividad y liberar recursos")
def informar_cierre(body: CierreIn, db: Session = Depends(get_db)):
    """Resta `cantidad_comprometida` de cada ítem. La misma referencia no se puede informar dos veces."""
    ong = db.scalar(
        select(Ong).where(Ong.cuit == body.cuit).options(selectinload(Ong.inventario))
    )
    if ong is None:
        raise HTTPException(status_code=404, detail="ONG no registrada")

    codigos = [i.tipo_recurso for i in body.items]
    if len(set(codigos)) != len(codigos):
        raise HTTPException(status_code=422, detail="Hay tipos de recurso repetidos")
    tipos = {t.codigo: t for t in db.scalars(select(TipoRecurso).where(TipoRecurso.codigo.in_(codigos)))}
    desconocidos = sorted(set(codigos) - tipos.keys())
    if desconocidos:
        raise HTTPException(status_code=404, detail=f"Tipo de recurso inexistente: {', '.join(desconocidos)}")

    ya = db.scalar(
        select(CierreOperativo.id).where(
            CierreOperativo.ong_id == ong.id, CierreOperativo.referencia == body.referencia
        )
    )
    if ya is not None:
        raise HTTPException(status_code=409, detail="Ese cierre ya fue informado")

    stmt = (
        select(Inventario)
        .where(
            Inventario.ong_id == ong.id,
            Inventario.tipo_recurso_id.in_([tipos[c].id for c in codigos]),
        )
        .order_by(Inventario.id)
        .options(selectinload(Inventario.tipo_recurso))
    )
    # En Postgres toma la fila; SQLite no tiene FOR UPDATE y los tests corren ahí.
    if db.get_bind().dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    filas = {f.tipo_recurso.codigo: f for f in db.scalars(stmt)}

    for item in body.items:
        fila = filas.get(item.tipo_recurso)
        bloqueados = 0 if fila is None else fila.cantidad_comprometida
        if fila is None or bloqueados < item.cantidad:
            raise HTTPException(
                status_code=409,
                detail=f"{item.tipo_recurso}: se pidió liberar {item.cantidad} y hay {bloqueados} bloqueados",
            )

    cierre = CierreOperativo(
        ong=ong, referencia=body.referencia, informado_en=datetime.now(timezone.utc)
    )
    for item in body.items:
        fila = filas[item.tipo_recurso]
        fila.cantidad_comprometida -= item.cantidad
        cierre.items.append(CierreItem(tipo_recurso=tipos[item.tipo_recurso], cantidad=item.cantidad))
    db.add(cierre)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese cierre ya fue informado") from None

    cargado = _cargar_cierre(db, cierre.id)
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
