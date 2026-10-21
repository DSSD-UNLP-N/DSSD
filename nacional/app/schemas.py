import enum
import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from app.models import CategoriaRecurso, EstadoAdjudicacion, EstadoOng, Riesgo

# Las columnas numéricas son INTEGER (32 bits): un valor mayor llegaría a Postgres y volvería como 500.
MAX_ENTERO = 2_147_483_647
Cantidad = Annotated[int, Field(gt=0, le=MAX_ENTERO)]
IdExterno = Annotated[int, Field(gt=0, le=MAX_ENTERO)]


def normalizar_cuit(valor):
    """`30546665445`, ` 30-54666544-5 ` y `30-54666544-5` son el mismo CUIT: se guarda y se busca como `NN-NNNNNNNN-N`.
    Lo que no tiene 11 dígitos se deja tal cual para que el patrón lo rechace."""
    if not isinstance(valor, str):
        return valor
    m = re.fullmatch(r"(\d{2})-?(\d{8})-?(\d)", valor.strip())
    return f"{m[1]}-{m[2]}-{m[3]}" if m else valor.strip()


Cuit = Annotated[str, BeforeValidator(normalizar_cuit), Field(pattern=r"^\d{2}-\d{8}-\d$")]
CuitPath = Annotated[str, BeforeValidator(normalizar_cuit)]  # en la ruta no se rechaza: un CUIT que no existe da 404


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterOngIn(BaseModel):
    ong_nombre: str = Field(min_length=2, max_length=120)
    cuit: Cuit
    nombre: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("ong_nombre", "nombre", "username", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def password_no_vacia(cls, value):
        if not value.strip():
            raise ValueError("La contraseña no puede ser solo espacios")
        return value


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
    tipo_recurso: str = Field(min_length=1)
    cantidad_total: int = Field(ge=0, le=MAX_ENTERO)


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
    cuit: Cuit
    tipo_recurso: str = Field(min_length=1)
    cantidad: Cantidad


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
    model_config = ConfigDict(str_strip_whitespace=True)

    cuit: Cuit
    referencia: str = Field(min_length=1, max_length=80)


class CierreLoteIn(BaseModel):
    """Los cierres de varias ONGs de una emergencia, para que un solo pedido de Bonita los resuelva."""
    cierres: list[CierreIn] = Field(min_length=1)


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
    inventario_id: IdExterno
    cantidad: Cantidad


class AdjudicacionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    referencia_id: str = Field(min_length=1, max_length=80)
    ong_id: IdExterno
    emergencia_id: IdExterno
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
    lote_id: IdExterno
    tipo_recurso: str | None = None  # None = lote anterior al catálogo: no se puede cubrir
    cantidad: Cantidad
    tipo: Literal["PRINCIPAL", "APOYO"] = "PRINCIPAL"


class ItemOfertaIn(BaseModel):
    lote_id: IdExterno
    tipo_recurso: str = Field(min_length=1)
    cantidad: Cantidad


class OfertaEvaluacionIn(BaseModel):
    cuit: Cuit
    ong: str | None = None
    version: int | None = None
    items: list[ItemOfertaIn] = Field(min_length=1)


class EvaluacionIn(BaseModel):
    emergencia_id: IdExterno
    ronda: int = Field(default=1, ge=1, le=MAX_ENTERO)
    gravedad: Riesgo
    lotes: list[LoteEvaluacionIn]
    ofertas: list[OfertaEvaluacionIn]

    @model_validator(mode="after")
    def lotes_y_ofertas_coherentes(self):
        """Cada lote una sola vez y cada ítem ofrecido apunta a un lote del pedido y de su mismo recurso: si no, se
        reservaría stock para algo que no se pidió o se contaría como cobertura de otro recurso."""
        ids = [l.lote_id for l in self.lotes]
        if len(set(ids)) != len(ids):
            raise ValueError("Hay lotes repetidos")
        por_id = {l.lote_id: l for l in self.lotes}
        for oferta in self.ofertas:
            for item in oferta.items:
                lote = por_id.get(item.lote_id)
                if lote is None:
                    raise ValueError(f"La oferta de {oferta.cuit} apunta al lote {item.lote_id}, que no está en el pedido")
                if lote.tipo_recurso != item.tipo_recurso:
                    raise ValueError(
                        f"La oferta de {oferta.cuit} ofrece {item.tipo_recurso} para el lote {item.lote_id}, "
                        f"que pide {lote.tipo_recurso}"
                    )
        return self


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
