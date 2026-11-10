"""Reporte del dashboard de indicadores (Auditor/Directivo)."""
from datetime import date, datetime

from pydantic import BaseModel


class Filtros(BaseModel):
    desde: date
    hasta: date
    municipio_id: int | None = None


class Kpis(BaseModel):
    emergencias: int
    resueltas: int
    en_curso: int
    pct_consorcio: float | None
    cobertura_promedio: float | None


class SuministroMes(BaseModel):
    mes: str  # "2026-10"
    tipo_recurso: str
    cantidad: int


class EstadoCantidad(BaseModel):
    estado: str
    etiqueta: str
    cantidad: int


class TiempoEtapa(BaseModel):
    tarea: str
    horas_promedio: float
    emergencias: int


class Tiempos(BaseModel):
    disponible: bool
    motivo: str | None
    etapas: list[TiempoEtapa]
    horas_total_promedio: float | None


class Finalizada(BaseModel):
    emergencia_id: int
    municipio: str
    tipo: str
    gravedad: str
    ongs: list[str]
    consorcio: bool
    horas_total: float | None
    cobertura: float | None


class Reporte(BaseModel):
    filtros: Filtros
    generado_en: datetime
    kpis: Kpis
    suministros: list[SuministroMes]
    estados: list[EstadoCantidad]
    tiempos: Tiempos
    finalizadas: list[Finalizada]
