from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import adjudicacion, auth, catalogo, cierre, inventario, reservas, validacion


async def sin_nul(request: Request):
    """Postgres no admite el carácter NUL en un texto: llegaría a la consulta y volvería como 500."""
    if "\x00" in request.url.path or "\x00" in unquote(request.url.query) or rb"\u0000" in await request.body():
        raise HTTPException(status_code=422, detail="Los textos no pueden contener el carácter NUL")


app = FastAPI(
    title=get_settings().app_name,
    description="API del Sistema Nacional: catálogo de recursos y certificaciones, inventario de las ONGs, "
    "validación de ofertas por niveles de competencia y cierre operativo (libera recursos bloqueados).",
    dependencies=[Depends(sin_nul)],
)


@app.exception_handler(RequestValidationError)
async def validacion_fallida(_: Request, exc: RequestValidationError):
    """Igual que el 422 de FastAPI pero sin devolver `input`: un `NaN` en el cuerpo no se puede volver a serializar."""
    errores = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errores)})


app.include_router(auth.router)
app.include_router(catalogo.router)
app.include_router(inventario.router)
app.include_router(validacion.router)
app.include_router(cierre.router)
app.include_router(reservas.router)
app.include_router(adjudicacion.router, prefix="/adjudicaciones", tags=["Adjudicaciones"])

@app.get("/health", tags=["estado"])
def health() -> dict[str, str]:
    return {"estado": "ok"}
