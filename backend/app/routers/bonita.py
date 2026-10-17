"""Endpoints que llama el motor de Bonita (conectores del proceso); sin sesión, con X-Api-Key."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.deps import require_bonita_key
from app.db import get_db
from app.schemas.evaluacion import EventoEvaluacion
from app.services.evaluacion import ConsolidadoError, consolidar_ofertas, guardar_evaluacion

router = APIRouter(prefix="/api/bonita", dependencies=[Depends(require_bonita_key)])


@router.get("/emergencias/{emergencia_id}/ofertas")
def consolidado_de_ofertas(emergencia_id: int, db: Session = Depends(get_db)):
    try:
        consolidado = consolidar_ofertas(db, emergencia_id)
    except ConsolidadoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if consolidado is None:
        raise HTTPException(status_code=404, detail="Emergencia no encontrada")
    return consolidado


@router.post("/emergencias/{emergencia_id}/eventos", status_code=status.HTTP_204_NO_CONTENT)
def evento_de_bonita(emergencia_id: int, evento: EventoEvaluacion, db: Session = Depends(get_db)):
    """Bonita avisa que evaluó las ofertas y manda el resultado de la API Nacional tal cual."""
    try:
        existe = guardar_evaluacion(db, emergencia_id, evento.resultado)
    except ConsolidadoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not existe:
        raise HTTPException(status_code=404, detail="Emergencia no encontrada")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
