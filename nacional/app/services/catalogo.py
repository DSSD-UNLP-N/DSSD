"""Reglas de competencia compartidas entre la ficha de la ONG y la validación."""
from datetime import date

from app.models import Ong, OngCertificacion, Riesgo, TipoRecurso


def certificacion_de(ong: Ong, tipo: TipoRecurso) -> OngCertificacion | None:
    """La certificación de la ONG que habilita el tipo de recurso, o None."""
    if tipo.certificacion_id is None:
        return None
    return next((c for c in ong.certificaciones if c.certificacion_id == tipo.certificacion_id), None)


def riesgo_permitido(ong: Ong, tipo: TipoRecurso, hoy: date) -> Riesgo | None:
    """Hasta qué riesgo puede operar la ONG este tipo de recurso.

    Sin certificación requerida (insumos) no hay límite; con ella, rige el `riesgo_max` si está
    vigente. None = la ONG no está certificada para este recurso (o la certificación venció)."""
    if tipo.certificacion_id is None:
        return Riesgo.CRITICO
    cert = certificacion_de(ong, tipo)
    if cert is None or cert.vence_el < hoy:
        return None
    return cert.riesgo_max
