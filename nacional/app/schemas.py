import enum
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models import CategoriaRecurso, EstadoAdjudicacion, EstadoOng, Riesgo


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterOngIn(BaseModel):
    ong_nombre: str = Field(min_length=2, max_length=120)
    cuit: str = Field(pattern=r"^\d{2}-?\d{8}-?\d$")
    nombre: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("ong_nombre", "nombre", "username", "cuit", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class CuentaOut(BaseModel):
    username: str
    rol: str
    cuit: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: CuentaOut


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


class CierreIn(BaseModel):
    cuit: str = Field(min_length=1, max_length=13)
    referencia: str = Field(min_length=1, max_length=80)


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
    estado: EstadoAdjudicacion
    items: list[AdjudicacionItemOut]


# --- Evaluación y reserva (eslabón 4): lo que Bonita manda tal cual lo recibió de la app local ---

class LoteEvaluacionIn(BaseModel):
    lote_id: int
    tipo_recurso: str | None = None  # None = lote anterior al catálogo: no se puede cubrir
    cantidad: int = Field(gt=0)
    tipo: str = "PRINCIPAL"


class ItemOfertaIn(BaseModel):
    lote_id: int
    tipo_recurso: str
    cantidad: int = Field(gt=0)


class OfertaEvaluacionIn(BaseModel):
    cuit: str = Field(min_length=1, max_length=13)
    ong: str | None = None
    version: int | None = None
    items: list[ItemOfertaIn] = Field(min_length=1)


class EvaluacionIn(BaseModel):
    emergencia_id: int = Field(gt=0)
    ronda: int = Field(default=1, ge=1)
    gravedad: Riesgo
    lotes: list[LoteEvaluacionIn]
    ofertas: list[OfertaEvaluacionIn]


class LoteCoberturaOut(BaseModel):
    lote_id: int
    tipo_recurso: str | None
    pedido: int
    reservado: int
    porcentaje: float
    cubierto: bool


class ItemEvaluadoOut(BaseModel):
    lote_id: int
    tipo_recurso: str
    ofrecido: int
    reservado: int
    nivel: NivelCompetencia
    riesgo_permitido: Riesgo | None
    asignacion_sugerida: Asignacion
    observaciones: list[str]


class OngEvaluadaOut(BaseModel):
    cuit: str
    ong: str | None
    referencia: str | None  # None = ONG no registrada: no hay nada reservado
    estado: str  # EstadoAdjudicacion, o NO_RESERVADA
    items: list[ItemEvaluadoOut]


class EvaluacionOut(BaseModel):
    emergencia_id: int
    ronda: int
    cobertura_completa: bool
    porcentaje_cobertura: float
    lotes: list[LoteCoberturaOut]
    ongs: list[OngEvaluadaOut]


class ReservaOut(BaseModel):
    referencia: str
    estado: EstadoAdjudicacion


class RecursoLiberadoOut(BaseModel):
    tipo_recurso: str
    cantidad: int


class LiberacionOut(ReservaOut):
    liberado: list[RecursoLiberadoOut]


class ResolucionIn(BaseModel):
    """La decisión del Municipio sobre las reservas de una emergencia: cuáles se confirman y cuáles se liberan."""
    confirmar: list[str] = Field(default_factory=list)
    liberar: list[str] = Field(default_factory=list)


class ResolucionOut(BaseModel):
    confirmadas: list[ReservaOut]
    liberadas: list[LiberacionOut]
