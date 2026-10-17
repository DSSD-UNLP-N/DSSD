"""Cliente de la API del Sistema Nacional (nacional/): catálogo de recursos y validación de ofertas.

Cualquier falla (red, timeout, respuesta no 2xx) sale como NacionalError, para que quien llama
decida: publicar una oferta sin validar nunca es una opción, así que la app responde 503.
"""
import requests
from fastapi import Depends

from app.core.config import Settings, get_settings


class NacionalError(RuntimeError):
    pass


class NacionalClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        try:
            resp = requests.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise NacionalError(f"Sistema Nacional: {method} {path} falló ({exc})") from exc

    def tipos_recurso(self) -> list[dict]:
        """Catálogo: [{codigo, nombre, categoria, unidad, certificacion_requerida}]."""
        return self._request("GET", "/tipos-recurso")

    def validar(self, gravedad: str, items: list[dict]) -> dict:
        """Valida cantidades y competencia (no guarda nada).

        items: [{cuit, tipo_recurso, cantidad}]. Devuelve {alcanza_todo, resultados: [{cuit, tipo_recurso,
        nombre_recurso, unidad, solicitado, disponible, alcanza, nivel, riesgo_permitido,
        asignacion_sugerida, observaciones}]}."""
        return self._request("POST", "/validaciones", json={"gravedad": gravedad, "items": items})

    def liberar(self, referencia: str) -> dict:
        """Libera una reserva (idempotente): la usa la app cuando el Coordinador reformula la convocatoria."""
        resultado = self._request("POST", f"/adjudicaciones/{referencia}/liberar")
        if not isinstance(resultado, dict):
            raise NacionalError("Sistema Nacional: respuesta inválida al liberar la reserva")
        return resultado

    def adjudicar_recursos_nacional(self, datos_adjudicacion: dict) -> dict:
        """Compromete recursos en el Sistema Nacional de forma idempotente."""
        resultado = self._request("POST", "/adjudicaciones", json=datos_adjudicacion)
        if not isinstance(resultado, dict):
            raise NacionalError("Sistema Nacional: respuesta inválida al adjudicar recursos")
        return resultado


def get_nacional(settings: Settings = Depends(get_settings)) -> NacionalClient:
    return NacionalClient(settings.nacional_base_url, settings.nacional_timeout_seconds)
