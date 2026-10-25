from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.integrations.nacional import NACIONAL_CAIDO, NacionalError
from app.routers import api, bonita
from app.services import ServicioError

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware, secret_key=settings.session_secret, same_site="lax", max_age=8 * 3600
)
app.include_router(api.router)
app.include_router(bonita.router)


@app.exception_handler(ServicioError)
async def _error_de_servicio(request: Request, exc: ServicioError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(NacionalError)
async def _nacional_caido(request: Request, exc: NacionalError) -> JSONResponse:
    return JSONResponse({"detail": NACIONAL_CAIDO}, status_code=503)
