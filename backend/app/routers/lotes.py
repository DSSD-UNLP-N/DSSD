from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.deps import require_role
from app.db import get_db
from app.models import Emergencia, Rol, Usuario
from app.schemas import mensaje_de_error
from app.schemas.lotes import ETIQUETAS, LoteIn, PublicacionIn
from app.services.emergencias import emergencia_visible
from app.services.lotes import (
    LoteError,
    PublicacionError,
    agregar_lote,
    borrar_lote,
    publicar_convocatoria,
)

router = APIRouter(prefix="/emergencias/{emergencia_id}")


def _emergencia(db: Session, user: Usuario, emergencia_id: int) -> Emergencia:
    emergencia = emergencia_visible(db, user, emergencia_id)
    if emergencia is None:
        raise HTTPException(status_code=404, detail="Emergencia no encontrada")
    return emergencia


def _volver(emergencia_id: int, error: str | None = None) -> RedirectResponse:
    """Siempre 303 al detalle (Post/Redirect/Get): recargar no repite la acción."""
    destino = f"/emergencias/{emergencia_id}"
    if error:
        destino += "?" + urlencode({"error": error})
    return RedirectResponse(destino, status_code=303)


@router.post("/lotes")
def crear_lote(
    emergencia_id: int,
    recurso: str = Form(""),
    cantidad: str = Form(""),
    unidad: str = Form(""),
    tipo: str = Form("PRINCIPAL"),
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
):
    emergencia = _emergencia(db, user, emergencia_id)
    try:
        datos = LoteIn(recurso=recurso, cantidad=cantidad, unidad=unidad, tipo=tipo)
    except ValidationError as exc:
        return _volver(emergencia_id, mensaje_de_error(exc, ETIQUETAS))
    try:
        agregar_lote(db, emergencia, datos)
    except LoteError as exc:
        return _volver(emergencia_id, str(exc))
    return _volver(emergencia_id)


@router.post("/lotes/{lote_id}/borrar")
def eliminar_lote(
    emergencia_id: int,
    lote_id: int,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
):
    emergencia = _emergencia(db, user, emergencia_id)
    try:
        borrar_lote(db, emergencia, lote_id)
    except LoteError as exc:
        return _volver(emergencia_id, str(exc))
    return _volver(emergencia_id)


@router.post("/publicar")
def publicar(
    emergencia_id: int,
    ventana_fin: str = Form(""),
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    emergencia = _emergencia(db, user, emergencia_id)
    try:
        datos = PublicacionIn(ventana_fin=ventana_fin)
    except ValidationError as exc:
        return _volver(emergencia_id, mensaje_de_error(exc, ETIQUETAS))
    try:
        publicar_convocatoria(
            db, settings, emergencia=emergencia, coordinador=user, ventana_fin=datos.ventana_fin)
    except PublicacionError as exc:
        return _volver(emergencia_id, str(exc))
    return _volver(emergencia_id)
