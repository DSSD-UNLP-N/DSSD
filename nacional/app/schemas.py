import enum
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import CategoriaRecurso, EstadoOng, Riesgo


class TipoRecursoOut(BaseModel):
    codigo: str
    nombre: str
    categoria: CategoriaRecurso
    unidad: str
    certificacion_requerida: str | None


class CertificacionOut(BaseModel):
    codigo: str
    nombre: str
    descripcion: str | None
    tipos_recurso: list[str]  # códigos de los tipos de recurso que habilita


class OngOut(BaseModel):
    cuit: str
    nombre: str
    estado: EstadoOng

    model_config = ConfigDict(from_attributes=True)


class OngCertificacionOut(BaseModel):
    codigo: str
    nombre: str
    riesgo_max: Riesgo
    vence_el: date
    vigente: bool


class InventarioOut(BaseModel):
    tipo_recurso: str
    nombre: str
    unidad: str
    cantidad_total: int
    cantidad_comprometida: int
    disponible: int
    # Hasta qué riesgo puede operar la ONG este recurso hoy; None si no tiene certificación vigente.
    riesgo_permitido: Riesgo | None


class FichaOngOut(OngOut):
    certificaciones: list[OngCertificacionOut]
    inventario: list[InventarioOut]


class DisponibilidadOngOut(BaseModel):
    cuit: str
    ong: str
    disponible: int


class DisponibilidadOut(BaseModel):
    tipo_recurso: str
    nombre: str
    unidad: str
    cantidad_total: int
    cantidad_comprometida: int
    disponible: int
    por_ong: list[DisponibilidadOngOut]


class InventarioItemIn(BaseModel):
    tipo_recurso: str
    cantidad_total: int = Field(ge=0)


class InventarioIn(BaseModel):
    items: list[InventarioItemIn] = Field(min_length=1)


class NivelCompetencia(str, enum.Enum):
    PLENA = "PLENA"  # certificación vigente y suficiente para la gravedad
    PARCIAL = "PARCIAL"  # certificación vigente pero de menor riesgo que la gravedad
    SUPERVISADA = "SUPERVISADA"  # sin certificación vigente (o ONG no habilitada)


class Asignacion(str, enum.Enum):
    PRINCIPAL = "PRINCIPAL"
    APOYO = "APOYO"


class ItemValidacionIn(BaseModel):
    cuit: str
    tipo_recurso: str
    cantidad: int = Field(gt=0)


class ValidacionIn(BaseModel):
    gravedad: Riesgo
    items: list[ItemValidacionIn] = Field(min_length=1)


class ResultadoValidacionOut(BaseModel):
    cuit: str
    ong: str | None  # None = ONG no registrada
    tipo_recurso: str
    nombre_recurso: str
    unidad: str
    solicitado: int
    disponible: int
    alcanza: bool
    nivel: NivelCompetencia
    riesgo_permitido: Riesgo | None
    asignacion_sugerida: Asignacion
    observaciones: list[str]


class ValidacionOut(BaseModel):
    alcanza_todo: bool
    resultados: list[ResultadoValidacionOut]


class CierreItemIn(BaseModel):
    tipo_recurso: str
    cantidad: int = Field(gt=0)


class CierreIn(BaseModel):
    cuit: str = Field(min_length=1, max_length=13)
    referencia: str = Field(min_length=1, max_length=80)
    items: list[CierreItemIn] = Field(min_length=1)


class CierreItemOut(BaseModel):
    tipo_recurso: str
    nombre: str
    unidad: str
    cantidad_liberada: int
    cantidad_total: int
    cantidad_comprometida: int
    disponible: int


class CierreOut(BaseModel):
    id: int
    cuit: str
    ong: str
    referencia: str
    informado_en: datetime
    items: list[CierreItemOut]


class AdjudicacionItemIn(BaseModel):
    inventario_id: int = Field(gt=0)
    cantidad: int = Field(gt=0)


class AdjudicacionIn(BaseModel):
    referencia_id: str = Field(min_length=1, max_length=80)
    ong_id: int = Field(gt=0)
    emergencia_id: int = Field(gt=0)
    items: list[AdjudicacionItemIn] = Field(min_length=1)


class AdjudicacionItemOut(BaseModel):
    inventario_id: int
    cantidad: int


class AdjudicacionOut(BaseModel):
    id: int
    referencia_id: str
    ong_id: int
    emergencia_id: int
    fecha_creacion: datetime
    items: list[AdjudicacionItemOut]
