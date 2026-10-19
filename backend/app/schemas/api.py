from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models import EstadoEmergencia, EstadoOferta, Gravedad, Rol, TipoLote
from app.schemas.evaluacion import Evaluacion


# SQLite descarta la zona y lo que se guarda siempre es UTC: sin esto el navegador lee la hora
# como local y la muestra corrida.
UtcDatetime = Annotated[
    datetime, AfterValidator(lambda d: d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d)
]


class UsuarioOut(BaseModel):
    id: int
    username: str
    nombre: str
    rol: Rol

    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TipoRecursoOut(BaseModel):
    codigo: str
    nombre: str
    categoria: str
    unidad: str
    certificacion_requerida: str | None = None


class LoteOut(BaseModel):
    id: int
    recurso: str
    tipo_recurso: str | None = None
    cantidad: int
    unidad: str
    tipo: TipoLote

    model_config = ConfigDict(from_attributes=True)


class OngEjecucionOut(BaseModel):
    cuit: str | None
    nombre: str
    estado: EstadoOferta  # ADJUDICADA mientras trabaja, FINALIZADA cuando informó que terminó


class EjecucionOut(BaseModel):
    """Cómo va la ejecución de una emergencia adjudicada. La ONG solo ve su propia fila."""
    monitoreo_iniciado: bool
    cierre_validado: bool
    todas_finalizadas: bool
    ongs: list[OngEjecucionOut]


class NotificacionOut(BaseModel):
    id: int
    emergencia_id: int
    texto: str
    creada_en: UtcDatetime
    leida: bool

    model_config = ConfigDict(from_attributes=True)


class EmergenciaOut(BaseModel):
    id: int
    tipo: str
    nivel_gravedad: Gravedad
    zona_afectada: str
    descripcion: str
    estado: EstadoEmergencia
    bonita_case_id: int | None
    ventana_ofertas_fin: UtcDatetime | None
    creada_en: UtcDatetime
    municipio_nombre: str | None = None
    municipio_provincia: str | None = None
    lotes: list[LoteOut] = []
    # Tarea que Bonita tiene pendiente para quien consulta; solo el detalle la completa.
    tarea_bonita: str | None = None
    # Cobertura y ofertas validadas por la API Nacional; solo el detalle la trae, y no para la ONG.
    evaluacion: Evaluacion | None = None
    # Ejecución y cierre; solo el detalle, y solo desde que la emergencia está en ejecución.
    ejecucion: EjecucionOut | None = None

    model_config = ConfigDict(from_attributes=True)


class DecisionIn(BaseModel):
    # PARCIAL: seguir con lo reservado. REFORMULAR: liberar todo y volver a cargar lotes (ronda siguiente).
    decision: Literal["PARCIAL", "REFORMULAR"]


class AdjudicarIn(BaseModel):
    cuits: list[str] = Field(min_length=1)  # las ONGs elegidas


class PublicarIn(BaseModel):
    ventana_fin: datetime


class OfertaItemIn(BaseModel):
    lote_id: int
    recurso: str = Field(min_length=1, max_length=120)
    cantidad: int = Field(gt=0)


class OfertaIn(BaseModel):
    # Cada envío es la oferta completa. Lista vacía = retirar la oferta (queda como versión nueva sin ítems).
    items: list[OfertaItemIn]


class OfertaItemOut(BaseModel):
    lote_id: int
    recurso: str
    cantidad: int
    version: int

    model_config = ConfigDict(from_attributes=True)


class OfertaOut(BaseModel):
    id: int
    emergencia_id: int
    ong_id: int
    ong_nombre: str
    version_actual: int
    items: list[OfertaItemOut]
    retirada: bool = False  # la versión vigente no tiene ítems
    estado: EstadoOferta = EstadoOferta.PRESENTADA

    model_config = ConfigDict(from_attributes=True)
