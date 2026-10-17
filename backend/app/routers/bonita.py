"""Endpoints que llama el motor de Bonita (conectores del proceso); sin sesión, con X-Api-Key."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.deps import require_bonita_key
from app.db import get_db
from app.schemas.evaluacion import Evento
from app.services.evaluacion import ConsolidadoError, consolidar_ofertas, guardar_evaluacion, registrar_adjudicacion, registrar_cierre

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
def evento_de_bonita(emergencia_id: int, evento: Evento, db: Session = Depends(get_db)):
    """Bonita avisa lo que hizo: evaluó las ofertas (EVALUACION) o resolvió las reservas (ADJUDICACION)."""
    try:
        if evento.tipo == "EVALUACION":
            existe = guardar_evaluacion(db, emergencia_id, evento.resultado)
        elif evento.tipo == "ADJUDICACION":
            existe = registrar_adjudicacion(db, emergencia_id, evento.adjudicadas, evento.no_adjudicadas)
        else:  # CIERRE
            existe = registrar_cierre(db, emergencia_id, evento.cuits)
    except ConsolidadoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not existe:
        raise HTTPException(status_code=404, detail="Emergencia no encontrada")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
