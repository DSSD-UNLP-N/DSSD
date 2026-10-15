from fastapi import FastAPI

from app.config import get_settings
from app.routers import adjudicacion, catalogo, cierre, inventario, validacion


app = FastAPI(
    title=get_settings().app_name,
    description="API del Sistema Nacional: catálogo de recursos y certificaciones, inventario de las ONGs, "
    "validación de ofertas por niveles de competencia y cierre operativo (libera recursos bloqueados).",
)

app.include_router(catalogo.router)
app.include_router(inventario.router)
app.include_router(validacion.router)
app.include_router(cierre.router)
app.include_router(adjudicacion.router, prefix="/adjudicaciones", tags=["Adjudicaciones"])

@app.get("/health", tags=["estado"])
def health() -> dict[str, str]:
    return {"estado": "ok"}
