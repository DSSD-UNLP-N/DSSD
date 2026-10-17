from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import TipoLote

ETIQUETAS = {
    "tipo_recurso": "Tipo de recurso",
    "detalle": "Detalle",
    "cantidad": "Cantidad",
    "tipo": "Tipo de lote",
    "ventana_fin": "Cierre de la ventana de ofertas",
}


class LoteIn(BaseModel):
    """El recurso se elige del catálogo del Sistema Nacional; el nombre y la unidad salen de ahí."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tipo_recurso: str = Field(min_length=1, max_length=40)
    detalle: str | None = Field(None, max_length=80)  # texto libre opcional, p. ej. "con equipo de trauma"
    cantidad: int = Field(gt=0)
    tipo: TipoLote = TipoLote.PRINCIPAL

    @field_validator("detalle")
    @classmethod
    def _detalle_vacio_es_none(cls, v: str | None) -> str | None:
        return v or None


class PublicacionIn(BaseModel):
    """La ventana la elige el Coordinador al publicar; el timer de Bonita la lee al activarse
    `Cargar Ofertas de Ayuda`, así que una fecha pasada cerraría la convocatoria al instante."""

    ventana_fin: datetime
