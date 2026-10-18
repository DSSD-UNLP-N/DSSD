"""Cliente de la API del Sistema Nacional (nacional/): catálogo de recursos y validación de ofertas.

Cualquier falla (red, timeout, respuesta no 2xx) sale como NacionalError, para que quien llama
decida: publicar una oferta sin validar nunca es una opción, así que la app responde 503.
"""
import requests
from fastapi import Depends, Request

from app.core.config import Settings, get_settings


class NacionalError(RuntimeError):
    pass


class NacionalLoginRejected(NacionalError):
    pass


class NacionalLoginEndpointMissing(NacionalError):
    pass


class NacionalClient:
    def __init__(self, base_url: str, timeout: float = 5.0, access_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.access_token = access_token

    def _request(self, method: str, path: str, *, authenticated: bool = True, **kwargs) -> dict | list:
        try:
            headers = dict(kwargs.pop("headers", {}))
            if authenticated and self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            resp = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                headers=headers,
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            message = f"Sistema Nacional: {method} {path} falló (HTTP {status_code})"
            if method == "POST" and path == "/login" and status_code == 401:
                raise NacionalLoginRejected(message) from exc
            if method == "POST" and path == "/login" and status_code == 404:
                raise NacionalLoginEndpointMissing(message) from exc
            raise NacionalError(message) from exc
        except (requests.RequestException, ValueError) as exc:
            raise NacionalError(f"Sistema Nacional: {method} {path} falló ({exc})") from exc

    def login(self, username: str, password: str) -> dict:
        resultado = self._request(
            "POST",
            "/login",
            authenticated=False,
            json={"username": username, "password": password},
        )
        if not isinstance(resultado, dict) or not isinstance(resultado.get("access_token"), str):
            raise NacionalError("Sistema Nacional: respuesta inválida al iniciar sesión")
        self.access_token = resultado["access_token"]
        return resultado

    def registrar_ong(self, datos: dict) -> dict:
        resultado = self._request("POST", "/ongs", authenticated=False, json=datos)
        if not isinstance(resultado, dict) or not isinstance(resultado.get("access_token"), str):
            raise NacionalError("Sistema Nacional: respuesta inválida al registrar la ONG")
        self.access_token = resultado["access_token"]
        return resultado

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


def get_nacional(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> NacionalClient:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    access_token = token if scheme.lower() == "bearer" and token else None
    return NacionalClient(settings.nacional_base_url, settings.nacional_timeout_seconds, access_token)
