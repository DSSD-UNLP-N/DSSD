"""Resultado de la evaluación, con el mismo formato que devuelve `POST /evaluaciones` de la API Nacional
(entrega-3/contratos.md, punto 3.1). Bonita lo reenvía tal cual a la app en un evento."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class LoteCobertura(BaseModel):
    lote_id: int
    tipo_recurso: str | None
    pedido: int
    reservado: int
    porcentaje: float
    cubierto: bool


class ItemEvaluado(BaseModel):
    lote_id: int
    tipo_recurso: str
    ofrecido: int
    reservado: int
    nivel: str  # PLENA | PARCIAL | SUPERVISADA
    riesgo_permitido: str | None
    asignacion_sugerida: str  # PRINCIPAL | APOYO
    observaciones: list[str]


class OngEvaluada(BaseModel):
    cuit: str
    ong: str | None
    referencia: str | None  # None = sin reserva (NO_RESERVADA): la ONG tiene que rehacer la oferta
    estado: str  # RESERVADA | ADJUDICADA | NO_RESERVADA
    items: list[ItemEvaluado]


class Evaluacion(BaseModel):
    emergencia_id: int
    ronda: int
    cobertura_completa: bool
    porcentaje_cobertura: float
    lotes: list[LoteCobertura]
    ongs: list[OngEvaluada]


class EventoEvaluacion(BaseModel):
    tipo: Literal["EVALUACION"]
    resultado: Evaluacion


class EventoAdjudicacion(BaseModel):
    """Bonita avisa que confirmó las reservas elegidas por el Municipio y liberó las demás."""
    tipo: Literal["ADJUDICACION"]
    adjudicadas: list[str]  # CUIT de las ONGs elegidas
    no_adjudicadas: list[str]  # CUIT de las demás ONGs evaluadas


class EventoCierre(BaseModel):
    """Bonita avisa que liberó en la API Nacional lo de cada ONG adjudicada: la emergencia queda resuelta."""
    tipo: Literal["CIERRE"]
    cuits: list[str] = Field(min_length=1)  # CUIT de las ONGs cuyo cierre se informó


Evento = Annotated[EventoEvaluacion | EventoAdjudicacion | EventoCierre, Field(discriminator="tipo")]

