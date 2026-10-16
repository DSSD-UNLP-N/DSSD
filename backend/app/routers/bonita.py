"""Endpoints que llama el motor de Bonita (conectores del proceso); sin sesión, con X-Api-Key."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_bonita_key
from app.db import get_db
from app.services.evaluacion import ConsolidadoError, consolidar_ofertas

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
