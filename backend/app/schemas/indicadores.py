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


class CursoAccion(BaseModel):
    curso: str  # TOTAL, PARCIAL, REFORMULAR o REABRIR
    etiqueta: str
    emergencias: int  # emergencias cuyo caso pasó por este curso (según las tareas completadas en Bonita)
    veces: int  # cuántas veces se tomó (una emergencia puede reformular o reabrir más de una vez)
    cobertura_promedio: float | None  # cobertura final de esas emergencias, de la base de la app


class Cursos(BaseModel):
    disponible: bool
    motivo: str | None
    filas: list[CursoAccion]


class Casos(BaseModel):
    """Estado del caso en Bonita contra el estado de la emergencia en la app."""
    disponible: bool
    motivo: str | None
    abiertos: int
    archivados: int
    consistentes: int
    inconsistentes: list[int]  # ids de emergencia: resuelta con el caso abierto, en curso con el caso cerrado o sin caso
    horas_resolucion_promedio: float | None  # Bonita: fin - inicio de los casos archivados


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
    cursos: Cursos
    casos: Casos
    finalizadas: list[Finalizada]
