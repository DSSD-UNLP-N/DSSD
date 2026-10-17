"""Resultado de la evaluación, con el mismo formato que devuelve `POST /evaluaciones` de la API Nacional
(entrega-3/contratos.md, punto 3.1). Bonita lo reenvía tal cual a la app en un evento."""
from typing import Literal

from pydantic import BaseModel


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
