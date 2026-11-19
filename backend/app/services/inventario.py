"""Inventario de la ONG que usa la app: vive en el Sistema Nacional, la app no guarda copia.

La ONG nunca entra a la API Nacional: la app lee la ficha y declara el inventario con su cuenta de servicio, porque
`PUT /ongs/{cuit}/inventario` solo la acepta a ella. El CUIT sale siempre de la ONG del usuario logueado, nunca del
pedido, así que una ONG no puede tocar el inventario de otra.
"""
from app.integrations.nacional import NacionalClient, NacionalError
from app.models import Ong
from app.schemas.api import RubroIn
from app.services import ServicioError

SIN_CUIT = "Tu ONG no tiene CUIT registrado en el Sistema Nacional."


def _cuit(ong: Ong | None) -> str:
    if ong is None or not ong.cuit:
        raise ServicioError(SIN_CUIT, 409)
    return ong.cuit


def ver(nacional: NacionalClient, ong: Ong | None) -> dict:
    """La ficha de la ONG: certificaciones e inventario. Si Nacional no responde sale NacionalError (503)."""
    cuit = _cuit(ong)
    try:
        return nacional.ficha_ong(cuit)
    except NacionalError as exc:
        if exc.status == 404:
            raise ServicioError("Tu ONG no está registrada en el Sistema Nacional.", 404) from exc
        raise


def declarar(nacional: NacionalClient, ong: Ong | None, rubros: list[RubroIn]) -> dict:
    """Fija el total de cada rubro y devuelve la ficha actualizada.

    Nacional rechaza con 409 bajar un total por debajo de lo comprometido y con 404 un tipo de recurso que no existe:
    los dos se informan con el detalle de Nacional (409 y 422). Cualquier otra falla sale como NacionalError (503)."""
    cuit = _cuit(ong)
    try:
        nacional.declarar_inventario(cuit, [r.model_dump() for r in rubros])
    except NacionalError as exc:
        if exc.status == 409:
            raise ServicioError(str(exc), 409) from exc
        if exc.status in (404, 422):
            raise ServicioError(str(exc), 422) from exc
        raise
    return ver(nacional, ong)
