from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ValidacionIn, ValidacionOut
from app.services.validacion import TipoRecursoDesconocido, validar

router = APIRouter(tags=["validación"])


@router.post("/validaciones", response_model=ValidacionOut, summary="Validar ofertas por cantidad y competencia")
def validar_ofertas(body: ValidacionIn, db: Session = Depends(get_db)):
    """Evalúa lo ofrecido por cada ONG contra su inventario disponible y su competencia para la
    gravedad de la emergencia. **No guarda nada**: las ofertas viven en la app local.

    Los ítems con la misma ONG y tipo de recurso se suman. Siempre responde 200 con un resultado
    estructurado: `alcanza` dice si la cantidad entra; `nivel` (PLENA, PARCIAL, SUPERVISADA) y
    `asignacion_sugerida` (PRINCIPAL, APOYO) expresan la competencia sin rechazos binarios."""
    try:
        resultados = validar(db, body.gravedad, body.items, date.today())
    except TipoRecursoDesconocido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ValidacionOut(alcanza_todo=all(r.alcanza for r in resultados), resultados=resultados)
