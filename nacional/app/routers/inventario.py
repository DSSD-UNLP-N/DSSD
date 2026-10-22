from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.errores import AUTH, errores
from app.models import Cuenta, Inventario, Ong, OngCertificacion, TipoRecurso
from app.routers.catalogo import inventario_out
from app.schemas import CuitPath, InventarioIn, InventarioOut
from app.security import require_ong_account

router = APIRouter(tags=["inventario"])


@router.put(
    "/ongs/{cuit}/inventario", response_model=list[InventarioOut],
    summary="Declarar el inventario de una ONG (upsert por tipo de recurso)",
    responses=errores({
        **AUTH,
        403: "La cuenta no es la de la ONG de la ruta (solo se modifica el inventario propio)",
        404: "La ONG o algún tipo de recurso no existe",
        409: "Se declara menos de lo que ya está comprometido",
    }),
)
def declarar_inventario(
    cuit: CuitPath,
    body: InventarioIn,
    db: Session = Depends(get_db),
    _cuenta: Cuenta = Depends(require_ong_account),
):
    """Fija `cantidad_total` por tipo de recurso. No toca `cantidad_comprometida`: no se puede declarar
    menos de lo ya comprometido (409). Devuelve el inventario completo de la ONG."""
    ong = db.scalar(
        select(Ong).where(Ong.cuit == cuit).options(
            selectinload(Ong.certificaciones).selectinload(OngCertificacion.certificacion),
            selectinload(Ong.inventario).selectinload(Inventario.tipo_recurso),
        )
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

    existentes = {i.tipo_recurso.codigo: i for i in ong.inventario}
    for item in body.items:
        fila = existentes.get(item.tipo_recurso)
        if fila is not None and item.cantidad_total < fila.cantidad_comprometida:
            raise HTTPException(
                status_code=409,
                detail=f"{item.tipo_recurso}: no se puede declarar {item.cantidad_total}, "
                f"hay {fila.cantidad_comprometida} comprometidos",
            )
    for item in body.items:
        fila = existentes.get(item.tipo_recurso)
        if fila is None:
            ong.inventario.append(Inventario(tipo_recurso=tipos[item.tipo_recurso], cantidad_total=item.cantidad_total))
        else:
            fila.cantidad_total = item.cantidad_total
    db.commit()
    db.refresh(ong)

    hoy = date.today()
    return [inventario_out(ong, i, hoy) for i in sorted(ong.inventario, key=lambda i: i.tipo_recurso.codigo)]
