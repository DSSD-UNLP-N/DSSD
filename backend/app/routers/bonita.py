"""Endpoints que llama el motor de Bonita (conectores del proceso); sin sesión, con X-Api-Key."""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.deps import require_bonita_key
from app.db import get_db
from app.schemas.evaluacion import Evento
from app.services.evaluacion import (
    consolidar_ofertas, guardar_evaluacion, registrar_adjudicacion, registrar_cierre,
)

router = APIRouter(prefix="/api/bonita", dependencies=[Depends(require_bonita_key)])


@router.get("/emergencias/{emergencia_id}/ofertas")
def consolidado_de_ofertas(emergencia_id: int, db: Session = Depends(get_db)):
    return consolidar_ofertas(db, emergencia_id)


@router.post("/emergencias/{emergencia_id}/eventos", status_code=status.HTTP_204_NO_CONTENT)
def evento_de_bonita(emergencia_id: int, evento: Evento, db: Session = Depends(get_db)):
    """Bonita avisa lo que hizo: evaluó las ofertas (EVALUACION), resolvió las reservas (ADJUDICACION) o liberó los
    recursos al cerrar (CIERRE)."""
    if evento.tipo == "EVALUACION":
        guardar_evaluacion(db, emergencia_id, evento.resultado)
    elif evento.tipo == "ADJUDICACION":
        registrar_adjudicacion(db, emergencia_id, evento.adjudicadas, evento.no_adjudicadas)
    else:
        registrar_cierre(db, emergencia_id, evento.cuits)
    # Explícito: sin esto FastAPI agrega `content-type: application/json` a un 204 sin cuerpo.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
