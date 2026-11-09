"""Router de indicadores del dashboard (solo rol AUDITOR).

Endpoints:
  GET  /api/indicadores                           → Reporte completo en JSON
  GET  /api/indicadores/export.csv?bloque=<b>     → CSV de un bloque

Filtros comunes: desde, hasta (YYYY-MM-DD; por defecto hoy-6 meses … hoy), municipio_id.
Si desde > hasta o la fecha es inválida: 422. Municipio_id inexistente: 200 con todo en cero.
Si Bonita falla: 200 con tiempos.disponible=False y motivo descriptivo.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.deps import get_bonita_lectura, require_role
from app.db import get_db
from app.models import Rol, Usuario
from app.schemas.indicadores import Filtros, Reporte
from app.services import indicadores as svc

router = APIRouter(prefix="/api/indicadores", tags=["indicadores"])

# ---------------------------------------------------------------------------
# Tipos de bloque para la exportación CSV
# ---------------------------------------------------------------------------

class Bloque(str, Enum):
    kpis = "kpis"
    suministros = "suministros"
    estados = "estados"
    tiempos = "tiempos"
    finalizadas = "finalizadas"


# Encabezados en castellano, definidos una vez por bloque
_ENCABEZADOS: dict[Bloque, list[str]] = {
    Bloque.kpis: [
        "Emergencias",
        "Resueltas",
        "En curso",
        "% Consorcio",
        "Cobertura promedio (%)",
    ],
    Bloque.suministros: ["Mes", "Tipo de recurso", "Cantidad"],
    Bloque.estados: ["Estado", "Etiqueta", "Cantidad"],
    Bloque.tiempos: ["Tarea", "Horas promedio", "Emergencias"],
    Bloque.finalizadas: [
        "ID",
        "Municipio",
        "Tipo",
        "Gravedad",
        "ONGs",
        "Consorcio",
        "Horas total (h)",
        "Cobertura (%)",
    ],
}

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _hoy() -> date:
    return date.today()


def _hace_seis_meses() -> date:
    return date.today() - timedelta(days=183)


def _validar_rango(desde: date, hasta: date) -> None:
    if desde > hasta:
        raise HTTPException(
            status_code=422,
            detail="El parámetro 'desde' no puede ser posterior a 'hasta'.",
        )


def _filtros(desde: date | None, hasta: date | None, municipio_id: int | None) -> Filtros:
    d = desde if desde is not None else _hace_seis_meses()
    h = hasta if hasta is not None else _hoy()
    _validar_rango(d, h)
    return Filtros(desde=d, hasta=h, municipio_id=municipio_id)


def _hacer_csv(encabezados: list[str], filas: list[list]) -> bytes:
    """Genera el CSV como bytes UTF-8 con BOM."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(encabezados)
    writer.writerows(filas)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def _respuesta_csv(contenido: bytes, bloque: str, desde: date, hasta: date) -> Response:
    nombre = f"indicadores_{bloque}_{desde}_{hasta}.csv"
    return Response(
        content=contenido,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


def _filas_csv(bloque: Bloque, reporte: Reporte) -> list[list]:
    if bloque is Bloque.kpis:
        k = reporte.kpis
        return [[
            k.emergencias,
            k.resueltas,
            k.en_curso,
            "" if k.pct_consorcio is None else k.pct_consorcio,
            "" if k.cobertura_promedio is None else k.cobertura_promedio,
        ]]
    if bloque is Bloque.suministros:
        return [[s.mes, s.tipo_recurso, s.cantidad] for s in reporte.suministros]
    if bloque is Bloque.estados:
        return [[e.estado, e.etiqueta, e.cantidad] for e in reporte.estados]
    if bloque is Bloque.tiempos:
        return [
            [t.tarea, t.horas_promedio, t.emergencias]
            for t in reporte.tiempos.etapas
        ]
    if bloque is Bloque.finalizadas:
        return [
            [
                f.emergencia_id,
                f.municipio,
                f.tipo,
                f.gravedad,
                "; ".join(f.ongs),
                "Sí" if f.consorcio else "No",
                "" if f.horas_total is None else f.horas_total,
                "" if f.cobertura is None else f.cobertura,
            ]
            for f in reporte.finalizadas
        ]
    return []  # nunca llega aquí; Bloque es enum exhaustivo


# ---------------------------------------------------------------------------
# Dependencias comunes de los endpoints
# ---------------------------------------------------------------------------

_SoloAuditor = Depends(require_role(Rol.AUDITOR))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=Reporte,
    summary="Reporte de indicadores del dashboard",
    description=(
        "Devuelve el reporte completo con KPIs, suministros por mes, emergencias por estado, "
        "tiempos por etapa de Bonita y listado de finalizadas. "
        "Si Bonita no está disponible, el bloque `tiempos` llega con `disponible=false` y `motivo`; "
        "el resto del reporte se calcula igualmente."
    ),
    responses={
        401: {"description": "Sin sesión activa."},
        403: {"description": "Solo el rol AUDITOR puede consultar los indicadores."},
        422: {"description": "'desde' posterior a 'hasta', o formato de fecha inválido."},
    },
    openapi_extra={
        "x-ejemplo-respuesta": {
            "filtros": {"desde": "2026-05-09", "hasta": "2026-11-09", "municipio_id": None},
            "generado_en": "2026-11-09T18:30:00Z",
            "kpis": {
                "emergencias": 14,
                "resueltas": 9,
                "en_curso": 5,
                "pct_consorcio": 33.3,
                "cobertura_promedio": 87.0,
            },
            "suministros": [
                {"mes": "2026-10", "tipo_recurso": "Raciones", "cantidad": 500},
            ],
            "estados": [
                {"estado": "RESUELTA", "etiqueta": "Resuelta", "cantidad": 9},
            ],
            "tiempos": {
                "disponible": True,
                "motivo": None,
                "etapas": [
                    {"tarea": "Adjudicar Ofertas", "horas_promedio": 6.5, "emergencias": 7}
                ],
                "horas_total_promedio": 48.3,
            },
            "finalizadas": [
                {
                    "emergencia_id": 3,
                    "municipio": "Bahía Blanca",
                    "tipo": "Inundación",
                    "gravedad": "ALTO",
                    "ongs": ["Cruz Roja Argentina"],
                    "consorcio": False,
                    "horas_total": 36.2,
                    "cobertura": 90.0,
                }
            ],
        }
    },
)
def api_indicadores(
    desde: Annotated[date | None, Query(description="Inicio del período (YYYY-MM-DD). Por defecto: hoy menos 6 meses.")] = None,
    hasta: Annotated[date | None, Query(description="Fin del período (YYYY-MM-DD). Por defecto: hoy.")] = None,
    municipio_id: Annotated[int | None, Query(description="Filtrar por municipio. Sin valor: todos los municipios.")] = None,
    user: Usuario = _SoloAuditor,
    db: Session = Depends(get_db),
    bonita=Depends(get_bonita_lectura),
) -> Reporte:
    f = _filtros(desde, hasta, municipio_id)
    return svc.reporte(db, bonita, f)


@router.get(
    "/export.csv",
    summary="Exportar un bloque del reporte como CSV",
    description=(
        "Devuelve un archivo CSV (UTF-8 con BOM) con un bloque del reporte. "
        "Bloques válidos: `kpis`, `suministros`, `estados`, `tiempos`, `finalizadas`. "
        "El nombre del archivo incluye el bloque y el rango: "
        "`indicadores_<bloque>_<desde>_<hasta>.csv`."
    ),
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV con BOM UTF-8, separador coma, encabezados en castellano.",
        },
        401: {"description": "Sin sesión activa."},
        403: {"description": "Solo el rol AUDITOR puede exportar los indicadores."},
        422: {"description": "Bloque inválido, 'desde' posterior a 'hasta', o formato de fecha inválido."},
    },
)
def api_indicadores_csv(
    bloque: Annotated[Bloque, Query(description="Bloque a exportar: kpis | suministros | estados | tiempos | finalizadas.")],
    desde: Annotated[date | None, Query(description="Inicio del período (YYYY-MM-DD). Por defecto: hoy menos 6 meses.")] = None,
    hasta: Annotated[date | None, Query(description="Fin del período (YYYY-MM-DD). Por defecto: hoy.")] = None,
    municipio_id: Annotated[int | None, Query(description="Filtrar por municipio. Sin valor: todos los municipios.")] = None,
    user: Usuario = _SoloAuditor,
    db: Session = Depends(get_db),
    bonita=Depends(get_bonita_lectura),
) -> Response:
    f = _filtros(desde, hasta, municipio_id)
    rep = svc.reporte(db, bonita, f)
    filas = _filas_csv(bloque, rep)
    contenido = _hacer_csv(_ENCABEZADOS[bloque], filas)
    return _respuesta_csv(contenido, bloque.value, f.desde, f.hasta)
