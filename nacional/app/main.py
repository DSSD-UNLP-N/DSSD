from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(
    title=get_settings().app_name,
    description="API del Sistema Nacional: catálogo de recursos y certificaciones, inventario de las ONGs "
    "y validación de ofertas por niveles de competencia.",
)


@app.get("/health", tags=["estado"])
def health() -> dict[str, str]:
    return {"estado": "ok"}
