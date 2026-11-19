"""Después de la evaluación: el Coordinador decide si la cobertura no alcanza y el Municipio adjudica.

Cada pantalla reemplaza a una tarea humana de Bonita ("Evaluar Cobertura y Definir Curso de Accion" y
"Adjudicar Ofertas"): la app setea la variable que lee el motor y completa la tarea con el usuario del rol.
Lo que sigue (confirmar y liberar las reservas, avisar a la app) lo hace Bonita sola con sus conectores.
"""
from __future__ import annotations

import json
from datetime import datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.integrations.bonita import BonitaError, bonita_login
from app.models import Emergencia, EstadoEmergencia, Oferta, Usuario
from app.schemas.evaluacion import Evaluacion
from app.services import ServicioError
from app.services.consorcios import consorcios_validos, miembros_aceptados
from app.services.lotes import TAREA_PUBLICAR, PublicacionError, publicar_convocatoria

TAREA_EVALUAR = "Evaluar Cobertura"
TAREA_ADJUDICAR = "Adjudicar Ofertas"
ESPERA_PUBLICAR = 120  # intentos de 0,5 s: al reabrir, Bonita libera en la API Nacional antes de llegar a «Publicar»


class CicloError(ServicioError):
    status = 409  # la operación no corresponde al estado; Bonita caída: 502


def _evaluacion(e: Emergencia) -> Evaluacion | None:
    return Evaluacion.model_validate_json(e.evaluacion) if e.evaluacion else None


def completar_en_bonita(settings: Settings, case_id: int | None, tarea: str, username: str,
                         variables: dict[str, str]) -> None:
    """Setea las variables del caso y completa la tarea con el usuario del rol (mismo username que en la app)."""
    if case_id is None:
        raise CicloError("La emergencia no tiene caso en Bonita.", 409)
    try:
        admin = bonita_login(settings)
        usuario = bonita_login(settings, username)
        pendiente = admin.wait_for_task(case_id, tarea)
        if pendiente is None:
            raise CicloError(f"El caso {case_id} no está esperando la tarea '{tarea}…' en Bonita.", 409)
        # Antes de completar la tarea: el motor lee las variables cuando sigue el flujo.
        for nombre, valor in variables.items():
            admin.set_case_variable(case_id, nombre, valor, "java.lang.String")
        usuario.complete_task_as_self(pendiente["id"])
    except (BonitaError, requests.RequestException) as exc:
        raise CicloError("No se pudo avanzar el caso en Bonita; probá de nuevo en un momento.", 502) from exc


def _retirar_ofertas(db: Session, emergencia: Emergencia) -> None:
    """Retira las ofertas de la ronda (versión nueva sin ítems): el historial queda."""
    ofertas = db.scalars(select(Oferta).where(Oferta.emergencia_id == emergencia.id).options(selectinload(Oferta.items)))
    for o in ofertas:
        if o.items_vigentes:
            o.version_actual += 1


def decidir(db: Session, settings: Settings, *, emergencia: Emergencia, coordinador: Usuario, decision: str,
            ventana_fin: datetime | None = None) -> None:
    """El Coordinador decide con la cobertura incompleta:
    - PARCIAL: sigue con lo reservado (el Municipio adjudica).
    - REFORMULAR: retira las ofertas, sube la ronda y vuelve a REGISTRADA para ajustar lotes y publicar de nuevo.
    - REABRIR: mismos lotes y ofertas; sube la ronda y vuelve a publicar con la ventana nueva (`ventana_fin`).
    En REFORMULAR y REABRIR las reservas de la ronda las libera Bonita (tarea de servicio «Liberar Reservas de la
    Ronda»): la app nunca llama a la API Nacional."""
    ev = _evaluacion(emergencia)
    if emergencia.estado is not EstadoEmergencia.EN_EVALUACION or ev is None:
        raise CicloError("La emergencia no está esperando una decisión del Coordinador.")
    if ev.cobertura_completa:
        raise CicloError("La cobertura está completa: no hay nada que decidir, el Municipio adjudica.")
    if decision == "REABRIR":
        if ventana_fin is None:
            raise CicloError("Para reabrir la convocatoria indicá el cierre de la nueva ventana.", 400)
        ventana_fin = ventana_fin if ventana_fin.tzinfo else ventana_fin.astimezone()
        if ventana_fin <= datetime.now().astimezone():
            raise CicloError("El cierre de la nueva ventana tiene que ser una fecha futura.", 400)

    completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_EVALUAR, coordinador.username,
                        {"decisionCoordinador": decision})

    if decision == "PARCIAL":
        emergencia.estado = EstadoEmergencia.ADJUDICACION
        db.commit()
        return
    if decision == "REFORMULAR":
        _retirar_ofertas(db, emergencia)
    emergencia.ronda += 1
    emergencia.estado = EstadoEmergencia.REGISTRADA
    emergencia.evaluacion = None
    emergencia.ventana_ofertas_fin = None
    db.commit()
    if decision == "REABRIR":
        # Bonita libera y llega a «Publicar Convocatoria» (salta «Revisar»: los lotes no cambian). Si la publicación
        # falla, la emergencia queda REGISTRADA con sus lotes y el Coordinador publica desde el formulario de siempre.
        # Antes de «Publicar» Bonita llama a la API Nacional (en Render puede tardar): se espera hasta un minuto.
        try:
            bonita_login(settings).wait_for_task(emergencia.bonita_case_id, TAREA_PUBLICAR, retries=ESPERA_PUBLICAR)
        except (BonitaError, requests.RequestException):
            pass  # publicar_convocatoria lo vuelve a intentar y, si no está, informa el error
        try:
            publicar_convocatoria(db, settings, emergencia=emergencia, coordinador=coordinador, ventana_fin=ventana_fin)
        except PublicacionError as exc:
            raise CicloError("Bonita reabrió la convocatoria pero no se pudo publicar la ventana nueva: "
                             "publicala desde el formulario de la emergencia.", 502) from exc


def adjudicar(db: Session, settings: Settings, *, emergencia: Emergencia, municipal: Usuario, cuits: list[str]) -> None:
    """El Municipio elige entre las ofertas validadas y reservadas. La app completa "Adjudicar Ofertas"; Bonita
    confirma lo elegido, libera lo demás y le avisa a la app (que recién ahí pasa a EN_EJECUCION)."""
    ev = _evaluacion(emergencia)
    if emergencia.estado is not EstadoEmergencia.ADJUDICACION or ev is None:
        raise CicloError("La emergencia no está esperando una adjudicación.")
    if not cuits or len(set(cuits)) != len(cuits):
        raise CicloError("Elegí al menos una ONG, sin repetirla.", 400)
    reservadas = {o.cuit for o in ev.ongs if o.estado == "RESERVADA"}
    invalidas = sorted(set(cuits) - reservadas)
    if invalidas:
        raise CicloError(
            f"No se puede adjudicar a {', '.join(invalidas)}: no tiene una oferta validada con stock reservado.", 400)
    for c in consorcios_validos(db, emergencia.id):
        miembros = miembros_aceptados(c)
        if not any(m.ong.cuit in cuits for m in miembros):
            continue
        faltan = [m.ong.nombre for m in miembros if m.ong.cuit in reservadas and m.ong.cuit not in cuits]
        if faltan:
            raise CicloError(f"El consorcio «{c.nombre}» se adjudica entero: falta {', '.join(faltan)}.", 409)
    completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_ADJUDICAR, municipal.username,
                         {"ongsAdjudicadas": json.dumps(cuits)})
