"""Respuestas de error que documenta Swagger. El cuerpo es siempre `{"detail": "..."}`; los 422 los documenta FastAPI."""
from pydantic import BaseModel, ConfigDict


class ErrorOut(BaseModel):
    detail: str

    model_config = ConfigDict(json_schema_extra={"examples": [{"detail": "Token inválido o vencido"}]})


AUTH = {401: "Token ausente, inválido o vencido: iniciar sesión de nuevo con `POST /login`"}
SERVICIO = {**AUTH, 403: "La cuenta no es de servicio (`bonita-service` o `app-service`)"}


def errores(descripciones: dict[int, str]) -> dict[int, dict]:
    """`responses=` de FastAPI a partir de {código: cuándo ocurre}."""
    return {codigo: {"model": ErrorOut, "description": texto} for codigo, texto in descripciones.items()}
