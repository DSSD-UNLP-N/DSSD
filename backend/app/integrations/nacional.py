"""Cliente de la API del Sistema Nacional (nacional/): catálogo de recursos y validación de ofertas.

Cualquier falla (red, timeout, respuesta no 2xx) sale como NacionalError, para que quien llama
decida: publicar una oferta sin validar nunca es una opción, así que la app responde 503.

La API exige JWT. La app entra con su propia cuenta de servicio (`app-service`), no con la de la persona que está
usando la pantalla: las personas se autentican contra la base de la app, y la app ya validó su rol antes de llamar.
El token se pide una vez por proceso y se renueva solo cuando Nacional contesta 401 (vencido o secreto rotado).
"""
import threading

import requests
from fastapi import Depends

from app.core.config import Settings, get_settings

# Un cliente nuevo por pedido, pero un solo login por proceso: (url, usuario) -> access_token.
_TOKENS: dict[tuple[str, str], str] = {}
_CANDADO = threading.Lock()


def olvidar_tokens() -> None:
    """Para los tests: que cada uno empiece sin sesión en Nacional."""
    with _CANDADO:
        _TOKENS.clear()


class NacionalError(RuntimeError):
    pass


class NacionalClient:
    def __init__(self, base_url: str, timeout: float = 5.0, username: str | None = None, password: str | None = None):
        """Sin usuario no manda token (para una API Nacional sin JWT)."""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.username = username or None
        self.password = password or ""

    def _token(self, renovar: bool = False) -> str | None:
        if self.username is None:
            return None
        clave = (self.base_url, self.username)
        with _CANDADO:
            if renovar or clave not in _TOKENS:
                try:
                    resp = requests.post(f"{self.base_url}/login", timeout=self.timeout,
                                         json={"username": self.username, "password": self.password})
                    resp.raise_for_status()
                    _TOKENS[clave] = resp.json()["access_token"]
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    raise NacionalError(
                        f"Sistema Nacional: no se pudo iniciar sesión como {self.username} ({exc})") from exc
            return _TOKENS[clave]

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        for renovar in (False, True):
            token = self._token(renovar)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                resp = requests.request(method, f"{self.base_url}{path}", timeout=self.timeout, headers=headers, **kwargs)
                if resp.status_code == 401 and token and not renovar:
                    continue  # vencido o secreto rotado: se vuelve a entrar una sola vez
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
    return NacionalClient(settings.nacional_base_url, settings.nacional_timeout_seconds,
                          settings.nacional_service_username, settings.nacional_service_password)
