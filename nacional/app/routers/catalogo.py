from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Certificacion, EstadoOng, Inventario, Ong, OngCertificacion, TipoRecurso
from app.schemas import (
    CertificacionOut,
    DisponibilidadOngOut,
    DisponibilidadOut,
    FichaOngOut,
    InventarioOut,
    OngCertificacionOut,
    OngOut,
    TipoRecursoOut,
)
from app.security import get_current_account
from app.services.catalogo import riesgo_permitido

router = APIRouter(tags=["catálogo"], dependencies=[Depends(get_current_account)])


def _tipo_out(t: TipoRecurso) -> TipoRecursoOut:
    return TipoRecursoOut(
        codigo=t.codigo, nombre=t.nombre, categoria=t.categoria, unidad=t.unidad,
        certificacion_requerida=t.certificacion.codigo if t.certificacion else None,
    )


def inventario_out(ong: Ong, i: Inventario, hoy: date) -> InventarioOut:
    return InventarioOut(
        tipo_recurso=i.tipo_recurso.codigo, nombre=i.tipo_recurso.nombre, unidad=i.tipo_recurso.unidad,
        cantidad_total=i.cantidad_total, cantidad_comprometida=i.cantidad_comprometida,
        disponible=i.disponible, riesgo_permitido=riesgo_permitido(ong, i.tipo_recurso, hoy),
    )


@router.get("/tipos-recurso", response_model=list[TipoRecursoOut], summary="Catálogo de tipos de recurso")
def listar_tipos_recurso(db: Session = Depends(get_db)):
    tipos = db.scalars(
        select(TipoRecurso).options(selectinload(TipoRecurso.certificacion)).order_by(TipoRecurso.codigo)
    ).all()
    return [_tipo_out(t) for t in tipos]


@router.get("/certificaciones", response_model=list[CertificacionOut], summary="Catálogo de certificaciones")
def listar_certificaciones(db: Session = Depends(get_db)):
    tipos = db.scalars(select(TipoRecurso).order_by(TipoRecurso.codigo)).all()
    return [
        CertificacionOut(
            codigo=c.codigo, nombre=c.nombre, descripcion=c.descripcion,
            tipos_recurso=[t.codigo for t in tipos if t.certificacion_id == c.id],
        )
        for c in db.scalars(select(Certificacion).order_by(Certificacion.codigo))
    ]


@router.get("/ongs", response_model=list[OngOut], summary="ONGs del registro nacional")
def listar_ongs(
    estado: EstadoOng | None = Query(None, description="Filtra por estado; HABILITADA = ONGs habilitadas"),
    db: Session = Depends(get_db),
):
    query = select(Ong).order_by(Ong.nombre)
    if estado is not None:
        query = query.where(Ong.estado == estado)
    return db.scalars(query).all()


@router.get("/ongs/{cuit}", response_model=FichaOngOut, summary="Ficha de una ONG")
def ficha_ong(cuit: str, db: Session = Depends(get_db)):
    ong = db.scalar(
        select(Ong).where(Ong.cuit == cuit).options(
            selectinload(Ong.certificaciones).selectinload(OngCertificacion.certificacion),
            selectinload(Ong.inventario).selectinload(Inventario.tipo_recurso),
        )
    )
    if ong is None:
        raise HTTPException(status_code=404, detail="ONG no registrada")
    hoy = date.today()
    return FichaOngOut(
        cuit=ong.cuit, nombre=ong.nombre, estado=ong.estado,
        certificaciones=[
            OngCertificacionOut(
                codigo=c.certificacion.codigo, nombre=c.certificacion.nombre, riesgo_max=c.riesgo_max,
                vence_el=c.vence_el, vigente=c.vence_el >= hoy,
            )
            for c in ong.certificaciones
        ],
        inventario=[inventario_out(ong, i, hoy) for i in sorted(ong.inventario, key=lambda i: i.tipo_recurso.codigo)],
    )


@router.get(
    "/recursos/disponibilidad", response_model=list[DisponibilidadOut],
    summary="Disponibilidad global de recursos (solo ONGs habilitadas)",
)
def disponibilidad(
    tipo_recurso: str | None = Query(None, description="Código del tipo de recurso; sin él, todos"),
    db: Session = Depends(get_db),
):
    query = select(TipoRecurso).order_by(TipoRecurso.codigo)
    if tipo_recurso is not None:
        query = query.where(TipoRecurso.codigo == tipo_recurso)
    tipos = db.scalars(query).all()
    if tipo_recurso is not None and not tipos:
        raise HTTPException(status_code=404, detail="Tipo de recurso inexistente")

    filas = db.scalars(
        select(Inventario)
        .join(Ong)
        .where(Ong.estado == EstadoOng.HABILITADA)
        .options(selectinload(Inventario.ong))
        .order_by(Ong.nombre)
    ).all()
    resultado = []
    for t in tipos:
        propias = [i for i in filas if i.tipo_recurso_id == t.id]
        resultado.append(
            DisponibilidadOut(
                tipo_recurso=t.codigo, nombre=t.nombre, unidad=t.unidad,
                cantidad_total=sum(i.cantidad_total for i in propias),
                cantidad_comprometida=sum(i.cantidad_comprometida for i in propias),
                disponible=sum(i.disponible for i in propias),
                por_ong=[
                    DisponibilidadOngOut(cuit=i.ong.cuit, ong=i.ong.nombre, disponible=i.disponible) for i in propias
                ],
            )
        )
    return resultado
