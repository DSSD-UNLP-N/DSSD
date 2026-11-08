from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.errores import SERVICIO, errores
from app.models import Inventario, Ong, OngCertificacion, TipoRecurso
from app.routers.catalogo import inventario_out, ong_o_404
from app.schemas import CuitPath, InventarioIn, InventarioOut
from app.security import require_servicio

# Solo el sistema (Bonita y la app local) carga el inventario: las ONGs no entran a esta API.
router = APIRouter(tags=["inventario"], dependencies=[Depends(require_servicio)], responses=errores(SERVICIO))


@router.put(
    "/ongs/{cuit}/inventario", response_model=list[InventarioOut],
    summary="Declarar el inventario de una ONG (upsert por tipo de recurso; solo el sistema)",
    responses=errores({
        404: "La ONG o algún tipo de recurso no existe",
        409: "Se declara menos de lo que ya está comprometido",
    }),
)
def declarar_inventario(
    cuit: CuitPath,
    body: InventarioIn,
    db: Session = Depends(get_db),
):
    """Fija `cantidad_total` por tipo de recurso. Lo llama el sistema (cuenta de servicio), nunca una cuenta de ONG.
    No toca `cantidad_comprometida`: no se puede declarar menos de lo ya comprometido (409).
    Devuelve el inventario completo de la ONG."""
    ong = ong_o_404(
        db, cuit,
        selectinload(Ong.certificaciones).selectinload(OngCertificacion.certificacion),
        selectinload(Ong.inventario).selectinload(Inventario.tipo_recurso),
    )

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
