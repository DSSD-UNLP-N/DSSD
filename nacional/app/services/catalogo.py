"""Consultas del catálogo y reglas de competencia compartidas con la validación."""
from datetime import date

from app.models import Ong, Riesgo, TipoRecurso


def riesgo_permitido(ong: Ong, tipo: TipoRecurso, hoy: date) -> Riesgo | None:
    """Hasta qué riesgo puede operar la ONG este tipo de recurso.

    Sin certificación requerida (insumos) no hay límite; con ella, rige el `riesgo_max` si está
    vigente. None = la ONG no está certificada para este recurso (o la certificación venció)."""
    if tipo.certificacion_id is None:
        return Riesgo.CRITICO
    cert = next((c for c in ong.certificaciones if c.certificacion_id == tipo.certificacion_id), None)
    if cert is None or cert.vence_el < hoy:
        return None
    return cert.riesgo_max
