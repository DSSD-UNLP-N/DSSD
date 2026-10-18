"""Evaluación de ofertas con reserva de stock, y su confirmación o liberación (los llama Bonita)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import EvaluacionIn, EvaluacionOut, LiberacionOut, ReservaOut, ResolucionIn, ResolucionOut
from app.security import require_bonita
from app.services import reservas
from app.services.validacion import TipoRecursoDesconocido

router = APIRouter(tags=["Reservas"], dependencies=[Depends(require_bonita)])


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, reservas.ReservaNoExiste):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, reservas.ReservaEnConflicto):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, TipoRecursoDesconocido):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


_ERRORES = (reservas.ReservaError, reservas.ReservaNoExiste, reservas.ReservaEnConflicto, TipoRecursoDesconocido)


@router.post("/evaluaciones", response_model=EvaluacionOut, summary="Evaluar las ofertas y reservar el stock")
def evaluar_ofertas(body: EvaluacionIn, db: Session = Depends(get_db)):
    """Al vencer la ventana de ofertas: valida a cada ONG (competencia contra la gravedad) y **reserva** lo que
    ofreció, sumando por recurso, hasta que se decida. Devuelve la cobertura por lote (promedio simple) y, por ONG,
    su referencia `emg-{emergencia}-r{ronda}-{cuit}`.

    Idempotente: repetir el pedido devuelve lo mismo sin reservar dos veces. Si lo ofrecido supera lo disponible
    se reserva lo que hay, recortando de los últimos ítems. `409` si la referencia ya fue liberada o cerrada."""
    try:
        try:
            return reservas.evaluar(db, body, date.today())
        except IntegrityError:
            # Dos pedidos iguales a la vez (reintento de Bonita): el otro ganó la referencia; esta vez la encuentra.
            db.rollback()
            return reservas.evaluar(db, body, date.today())
    except _ERRORES as exc:
        raise _http(exc) from exc


@router.post("/adjudicaciones/{referencia}/confirmar", response_model=ReservaOut,
             summary="Confirmar una reserva (compromiso nacional)")
def confirmar_reserva(referencia: str, db: Session = Depends(get_db)):
    """`RESERVADA` → `ADJUDICADA`. No toca el stock. Repetirlo responde 200; `409` si ya estaba liberada o cerrada."""
    try:
        adj = reservas.confirmar(db, referencia)
    except _ERRORES as exc:
        raise _http(exc) from exc
    return ReservaOut(referencia=adj.referencia_id, estado=adj.estado)


@router.post("/adjudicaciones/{referencia}/liberar", response_model=LiberacionOut,
             summary="Liberar una reserva y devolver el stock")
def liberar_reserva(referencia: str, db: Session = Depends(get_db)):
    """`RESERVADA` o `ADJUDICADA` → `LIBERADA` y resta lo bloqueado del inventario. Repetirlo responde 200 sin
    restar de nuevo; `409` si ya estaba cerrada."""
    try:
        return reservas.liberar(db, referencia)
    except _ERRORES as exc:
        raise _http(exc) from exc


@router.post("/adjudicaciones/resolucion", response_model=ResolucionOut,
             summary="Confirmar las reservas elegidas y liberar las demás, en una sola llamada")
def resolver_reservas(body: ResolucionIn, db: Session = Depends(get_db)):
    """Lo que Bonita manda cuando el Municipio adjudica: `confirmar` pasa cada referencia a `ADJUDICADA` y `liberar`
    devuelve el stock de las demás. Valida todo antes de cambiar nada (`404` si una referencia no existe, `409` si
    alguna ya no admite la operación) y es idempotente: repetir la llamada completa no resta dos veces."""
    try:
        return reservas.resolver(db, body.confirmar, body.liberar)
    except _ERRORES as exc:
        raise _http(exc) from exc
