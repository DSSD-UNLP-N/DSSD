"""Pedidos a la API Nacional con el JWT de la cuenta de servicio, para los escenarios que la consultan o la tocan directo.

La API exige token. La app y Bonita entran con sus cuentas de servicio; los escenarios entran como la app (`app-service`,
la misma cuenta que usa el backend: sale de NACIONAL_SERVICE_USERNAME / NACIONAL_SERVICE_PASSWORD) y, si Nacional
contesta 401 porque el token venció, vuelven a entrar una sola vez.

    from nacional_auth import nacional_get, nacional_post
    ficha = nacional_get(f"{nacional}/ongs/{cuit}", timeout=60).json()
"""
from __future__ import annotations

import requests


def _cabeceras(renovar: bool = False) -> dict[str, str]:
    from app.core.config import get_settings
    from app.integrations.nacional import NacionalClient

    cfg = get_settings()
    cliente = NacionalClient(cfg.nacional_base_url, 60, cfg.nacional_service_username, cfg.nacional_service_password)
    token = cliente._token(renovar)
    return {"Authorization": f"Bearer {token}"} if token else {}


def nacional_pedir(metodo: str, url: str, **kwargs) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}))
    for renovar in (False, True):
        respuesta = requests.request(metodo, url, headers={**_cabeceras(renovar), **headers}, **kwargs)
        if respuesta.status_code != 401:
            break
    return respuesta


def nacional_get(url: str, **kwargs) -> requests.Response:
    return nacional_pedir("GET", url, **kwargs)


def nacional_post(url: str, **kwargs) -> requests.Response:
    return nacional_pedir("POST", url, **kwargs)
