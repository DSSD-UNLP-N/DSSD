"""Validación de ofertas: cantidades disponibles y nivel de competencia.

No guarda nada (las ofertas viven en la app local). Para cada (ONG, tipo de recurso) responde:
- si lo pedido alcanza con el inventario disponible a nivel nacional, y
- con qué nivel de competencia opera la ONG según la gravedad de la emergencia; sin rechazos
  binarios: una competencia menor degrada la oferta a apoyo en vez de descartarla.
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import EstadoOng, Inventario, Ong, OngCertificacion, Riesgo, TipoRecurso
from app.schemas import Asignacion, ItemValidacionIn, NivelCompetencia, ResultadoValidacionOut
from app.services.catalogo import certificacion_de, riesgo_permitido

_ORDEN = {r: i for i, r in enumerate(Riesgo)}


class TipoRecursoDesconocido(ValueError):
    pass


def validar(db: Session, gravedad: Riesgo, items: list[ItemValidacionIn], hoy: date) -> list[ResultadoValidacionOut]:
    # Lo que una ONG ofrece del mismo recurso en varios ítems (lotes, emergencias) se suma.
    pedido: dict[tuple[str, str], int] = defaultdict(int)
    for item in items:
        pedido[(item.cuit, item.tipo_recurso)] += item.cantidad

    codigos = {codigo for _, codigo in pedido}
    tipos = {
        t.codigo: t
        for t in db.scalars(
            select(TipoRecurso).where(TipoRecurso.codigo.in_(codigos)).options(selectinload(TipoRecurso.certificacion))
        )
    }
    desconocidos = sorted(codigos - tipos.keys())
    if desconocidos:
        raise TipoRecursoDesconocido(f"Tipo de recurso inexistente: {', '.join(desconocidos)}")

    ongs = {
        o.cuit: o
        for o in db.scalars(
            select(Ong).where(Ong.cuit.in_({cuit for cuit, _ in pedido})).options(
                selectinload(Ong.certificaciones).selectinload(OngCertificacion.certificacion),
                selectinload(Ong.inventario),
            )
        )
    }

    return [
        _resultado(cuit, ongs.get(cuit), tipos[codigo], cantidad, gravedad, hoy)
        for (cuit, codigo), cantidad in pedido.items()
    ]


def _resultado(
    cuit: str, ong: Ong | None, tipo: TipoRecurso, solicitado: int, gravedad: Riesgo, hoy: date
) -> ResultadoValidacionOut:
    observaciones: list[str] = []
    habilitada = ong is not None and ong.estado is EstadoOng.HABILITADA

    # Cantidad: una ONG no registrada o suspendida no puede comprometer nada.
    fila: Inventario | None = next((i for i in ong.inventario if i.tipo_recurso_id == tipo.id), None) if ong else None
    disponible = fila.disponible if fila is not None and habilitada else 0
    alcanza = solicitado <= disponible
    if not alcanza:
        observaciones.append(f"Solicitado {solicitado}, disponible {disponible}")

    # Competencia.
    if ong is None:
        observaciones.append("ONG no registrada en el Sistema Nacional")
    elif not habilitada:
        observaciones.append("ONG suspendida: no está habilitada para comprometer recursos")
    riesgo = riesgo_permitido(ong, tipo, hoy) if habilitada else None

    if riesgo is None:
        nivel, asignacion = NivelCompetencia.SUPERVISADA, Asignacion.APOYO
        if habilitada:
            cert = certificacion_de(ong, tipo)
            requerida = tipo.certificacion.codigo
            observaciones.append(
                f"Certificación {requerida} vencida el {cert.vence_el}" if cert else f"Sin certificación {requerida}"
            )
    elif _ORDEN[riesgo] >= _ORDEN[gravedad]:
        nivel, asignacion = NivelCompetencia.PLENA, Asignacion.PRINCIPAL
    else:
        nivel, asignacion = NivelCompetencia.PARCIAL, Asignacion.APOYO
        observaciones.append(
            f"{tipo.certificacion.codigo} vigente hasta riesgo {riesgo.value}; la emergencia es {gravedad.value}"
        )

    return ResultadoValidacionOut(
        cuit=cuit, ong=ong.nombre if ong else None, tipo_recurso=tipo.codigo,
        solicitado=solicitado, disponible=disponible, alcanza=alcanza,
        nivel=nivel, riesgo_permitido=riesgo, asignacion_sugerida=asignacion, observaciones=observaciones,
    )
