from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

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
    # Consorcio válido al que pertenece la ONG en esta emergencia (None si no tiene o todavía no es válido).
    consorcio_id: int | None = None
    consorcio_nombre: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RubroIn(BaseModel):
    tipo_recurso: str = Field(min_length=1)
    cantidad_total: int = Field(ge=0)


class AltaOngIn(BaseModel):
    ong_nombre: str = Field(min_length=2, max_length=120)
    cuit: str = Field(pattern=r"^\d{2}-?\d{8}-?\d$")
    nombre: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")  # lo mismo que exige la API Nacional
    password: str = Field(min_length=8, max_length=128)
    rubros: list[RubroIn] = Field(min_length=1)

    @field_validator("ong_nombre", "cuit", "nombre", "username", mode="before")
    @classmethod
    def _recortar(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("rubros")
    @classmethod
    def _sin_repetidos(cls, v):
        tipos = [r.tipo_recurso for r in v]
        if len(set(tipos)) != len(tipos):
            raise ValueError("No repitas el mismo tipo de recurso")
        return v


class AltaOngOut(BaseModel):
    ong_nombre: str
    cuit: str
    username: str
    rubros: list[RubroIn]


class ConsorcioIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=80, description="Nombre único dentro de la emergencia.")

    model_config = ConfigDict(str_strip_whitespace=True, json_schema_extra={"examples": [{"nombre": "Alianza Norte"}]})


class InvitacionIn(BaseModel):
    ong_id: int = Field(ge=1, le=2_147_483_647, description="Id de la ONG invitada (ver GET /api/ongs).")

    model_config = ConfigDict(json_schema_extra={"examples": [{"ong_id": 2}]})


class RespuestaIn(BaseModel):
    acepta: bool = Field(description="true acepta la invitación; false la rechaza.")

    model_config = ConfigDict(json_schema_extra={"examples": [{"acepta": True}]})


class MiembroOut(BaseModel):
    ong_id: int
    ong_nombre: str
    cuit: str | None
    estado: str = Field(description="INVITADA, ACEPTADA, RECHAZADA o SALIO.")
    invitado_en: UtcDatetime
    respondido_en: UtcDatetime | None
    salio_en: UtcDatetime | None


class ConsorcioOut(BaseModel):
    id: int
    emergencia_id: int
    nombre: str
    ong_lider_id: int
    ong_lider_nombre: str
    valido: bool = Field(description="Tiene 2 o más miembros aceptados y no está disuelto.")
    disuelto: bool
    miembros: list[MiembroOut]

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id": 1, "emergencia_id": 7, "nombre": "Alianza Norte", "ong_lider_id": 1,
        "ong_lider_nombre": "Cruz Roja Argentina", "valido": False, "disuelto": False,
        "miembros": [{"ong_id": 1, "ong_nombre": "Cruz Roja Argentina", "cuit": "30-54666544-5",
                      "estado": "ACEPTADA", "invitado_en": "2026-11-08T12:00:00Z",
                      "respondido_en": "2026-11-08T12:00:00Z", "salio_en": None}],
    }]})


class OngOut(BaseModel):
    id: int
    nombre: str
    cuit: str | None

    model_config = ConfigDict(from_attributes=True, json_schema_extra={
        "examples": [{"id": 2, "nombre": "Bomberos Voluntarios", "cuit": "30-68522415-9"}]})
