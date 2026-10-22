from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errores import errores
from app.routers import adjudicacion, auth, catalogo, cierre, inventario, reservas, validacion


async def sin_nul(request: Request):
    """Postgres no admite el carácter NUL en un texto: llegaría a la consulta y volvería como 500."""
    if "\x00" in request.url.path or "\x00" in unquote(request.url.query) or rb"\u0000" in await request.body():
        raise HTTPException(status_code=422, detail="Los textos no pueden contener el carácter NUL")


app = FastAPI(
    title=get_settings().app_name,
    version="1.0.0",
    description="API del Sistema Nacional: catálogo de recursos y certificaciones, inventario de las ONGs, "
    "validación de ofertas por niveles de competencia y cierre operativo (libera recursos bloqueados).\n\n"
    "**Autenticación.** `POST /login` devuelve un JWT; en Swagger, botón *Authorize* y pegar el token. Todo menos "
    "`/health`, `/login` y `POST /ongs` lo exige. Los endpoints de reservas, adjudicaciones y cierres son solo de las "
    "cuentas de servicio (Bonita y la app local); el inventario lo modifica cada ONG con su cuenta.\n\n"
    "**Recorrido de una emergencia.** `POST /validaciones` (consulta, no guarda) → `POST /evaluaciones` (reserva el stock "
    "al vencer la ventana de ofertas) → `POST /adjudicaciones/resolucion` (confirma las elegidas y libera las demás) → "
    "`POST /cierres/lote` (cierra y devuelve lo comprometido).\n\n"
    "**Errores.** Siempre `{\"detail\": ...}`. Datos mal formados: 422 (nada se guarda). Sin token o vencido: 401. "
    "Cuenta sin permiso: 403. No existe: 404. Choca con el estado actual: 409. Las operaciones de reserva y cierre son "
    "idempotentes: repetirlas devuelve el mismo resultado sin volver a restar stock.",
    openapi_tags=[
        {"name": "autenticación", "description": "Login con JWT y alta de ONGs (servicio 1)."},
        {"name": "catálogo", "description": "Tipos de recurso, certificaciones, ONGs y disponibilidad (servicio 2)."},
        {"name": "inventario", "description": "Cada ONG declara lo que tiene (servicio 2)."},
        {"name": "validación", "description": "Competencia y cantidad de lo ofrecido, sin rechazos binarios (servicio 3)."},
        {"name": "reservas", "description": "Evaluación con reserva de stock y su confirmación o liberación (servicio 4)."},
        {"name": "adjudicaciones", "description": "Compromiso de inventario con bloqueo pesimista (servicio 4)."},
        {"name": "cierre", "description": "Fin de la actividad: libera lo comprometido (servicio 5)."},
        {"name": "estado", "description": "Salud del servicio."},
    ],
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
app.include_router(adjudicacion.router, prefix="/adjudicaciones", tags=["adjudicaciones"])

@app.get("/health", tags=["estado"], summary="Estado del servicio")
def health() -> dict[str, str]:
    """Responde `{"estado": "ok"}` sin autenticación. En Render (plan gratis) la primera llamada tras un rato de inactividad tarda 30-60 s."""
    return {"estado": "ok"}
