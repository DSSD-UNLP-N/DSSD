"""T-10: lotes de necesidades y publicación de la convocatoria (Centro Coordinador).

La pantalla del Coordinador reemplaza a dos tareas de Bonita seguidas
("Revisar Informacion y Generar Lotes…" y "Publicar Convocatoria…"), así que al publicar
la app completa las dos en nombre del Coordinador. Mientras tanto los lotes viven solo en
la base local y el caso espera en la primera tarea.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.bonita import BonitaClient, BonitaError
from app.models import Emergencia, EstadoEmergencia, Lote, Usuario
from app.schemas.lotes import LoteIn

TAREA_REVISAR = "Revisar Informacion"
TAREA_PUBLICAR = "Publicar Convocatoria"


class LoteError(RuntimeError):
    """Operación inválida sobre los lotes (estado equivocado, lote inexistente…)."""


class PublicacionError(RuntimeError):
    """La convocatoria no pudo publicarse; la emergencia queda como estaba."""


def _editable(emergencia: Emergencia) -> None:
    if emergencia.estado is not EstadoEmergencia.REGISTRADA:
        raise LoteError("La convocatoria ya está publicada: los lotes no se pueden modificar.")


def agregar_lote(db: Session, emergencia: Emergencia, datos: LoteIn) -> Lote:
    _editable(emergencia)
    lote = Lote(emergencia_id=emergencia.id, **datos.model_dump())
    db.add(lote)
    db.commit()
    db.refresh(lote)
    return lote


def borrar_lote(db: Session, emergencia: Emergencia, lote_id: int) -> None:
    _editable(emergencia)
    lote = next((lote for lote in emergencia.lotes if lote.id == lote_id), None)
    if lote is None:
        raise LoteError("Ese lote no pertenece a esta emergencia.")
    db.delete(lote)
    db.commit()


def publicar_convocatoria(
    db: Session, settings: Settings, *, emergencia: Emergencia, coordinador: Usuario, ventana_fin: datetime
) -> Emergencia:
    if emergencia.estado is not EstadoEmergencia.REGISTRADA:
        raise PublicacionError("Esta convocatoria ya fue publicada.")
    if not emergencia.lotes:
        raise PublicacionError("Agregá al menos un lote antes de publicar la convocatoria.")
    if emergencia.bonita_case_id is None:
        raise PublicacionError("La emergencia no tiene caso en Bonita; no se puede publicar.")
    if ventana_fin.tzinfo is None:
        ventana_fin = ventana_fin.astimezone()
    if ventana_fin <= datetime.now().astimezone():
        raise PublicacionError("El cierre de la ventana tiene que ser una fecha futura.")

    try:
        publicar_en_bonita(settings, emergencia.bonita_case_id, ventana_fin, coordinador.username)
    except (BonitaError, requests.RequestException) as exc:
        db.rollback()
        raise PublicacionError(
            "No se pudo publicar la convocatoria en Bonita. La emergencia quedó sin publicar; probá de nuevo."
        ) from exc

    # Siempre UTC: SQLite descarta la zona y guardaría la hora local como si fuera UTC.
    emergencia.ventana_ofertas_fin = ventana_fin.astimezone(timezone.utc)
    emergencia.estado = EstadoEmergencia.CONVOCATORIA
    db.commit()
    db.refresh(emergencia)
    return emergencia


def publicar_en_bonita(settings: Settings, case_id: int, ventana_fin: datetime, coordinador_username: str) -> None:
    """Completa "Revisar…" (si sigue pendiente), setea la ventana y completa "Publicar…".

    Lo administrativo (leer tareas, setear la variable) va con el usuario técnico; las tareas
    humanas las ejecuta el coordinador que publicó, para que el motor lo registre a él."""
    admin = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    admin.login(settings.bonita_username, settings.bonita_password)
    coordinador = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    coordinador.login(coordinador_username, settings.bonita_test_password)

    # Si un intento anterior se cortó después de completar "Revisar…", el caso ya está en
    # "Publicar…": se sigue desde ahí en vez de fallar.
    revisar = admin.find_task(case_id, TAREA_REVISAR)
    if revisar is not None:
        coordinador.complete_task_as_self(revisar["id"])

    publicar = admin.wait_for_task(case_id, TAREA_PUBLICAR)
    if publicar is None:
        raise BonitaError(f"El caso {case_id} no está en '{TAREA_PUBLICAR}…'; no se puede publicar.")

    # Antes de completar "Publicar…": el timer lee la variable al activarse "Cargar Ofertas de Ayuda".
    admin.set_case_variable(
        case_id, "ventanaOfertasISO", ventana_fin.isoformat(timespec="seconds"), "java.lang.String"
    )
    coordinador.complete_task_as_self(publicar["id"])
