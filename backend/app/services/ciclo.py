"""Después de la evaluación: el Coordinador decide si la cobertura no alcanza y el Municipio adjudica.

Cada pantalla reemplaza a una tarea humana de Bonita ("Evaluar Cobertura y Definir Curso de Accion" y
"Adjudicar Ofertas"): la app setea la variable que lee el motor y completa la tarea con el usuario del rol.
Lo que sigue (confirmar y liberar las reservas, avisar a la app) lo hace Bonita sola con sus conectores.
"""
from __future__ import annotations

import json

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload  # noqa: F401 (selectinload usado en _ofertas_adjudicadas)

from app.core.config import Settings
from app.integrations.bonita import BonitaClient, BonitaError
from app.integrations.nacional import NacionalClient
from app.models import Emergencia, EstadoEmergencia, EstadoOferta, Oferta, Ong, Usuario
from app.schemas.evaluacion import Evaluacion

TAREA_EVALUAR = "Evaluar Cobertura"
TAREA_ADJUDICAR = "Adjudicar Ofertas"
TAREA_MONITOREAR = "Monitorear Ejecucion del Despliegue"
TAREA_CONFIRMAR = "Confirmar Finalizacion de Actividades"
TAREA_VALIDAR = "Validar Cierre Operativo Bilateral"


class CicloError(RuntimeError):
    """La operación no corresponde (estado equivocado, datos inválidos) o Bonita no pudo avanzar el caso."""

    def __init__(self, mensaje: str, status: int = 409):
        super().__init__(mensaje)
        self.status = status


def _evaluacion(e: Emergencia) -> Evaluacion | None:
    return Evaluacion.model_validate_json(e.evaluacion) if e.evaluacion else None


def _completar_en_bonita(settings: Settings, case_id: int | None, tarea: str, username: str,
                         variables: dict[str, str]) -> None:
    """Setea las variables del caso y completa la tarea con el usuario del rol (mismo username que en la app)."""
    if case_id is None:
        raise CicloError("La emergencia no tiene caso en Bonita.", 409)
    try:
        admin = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
        admin.login(settings.bonita_username, settings.bonita_password)
        usuario = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
        usuario.login(username, settings.bonita_test_password)
        pendiente = admin.wait_for_task(case_id, tarea)
        if pendiente is None:
            raise CicloError(f"El caso {case_id} no está esperando la tarea '{tarea}…' en Bonita.", 409)
        # Antes de completar la tarea: el motor lee las variables cuando sigue el flujo.
        for nombre, valor in variables.items():
            admin.set_case_variable(case_id, nombre, valor, "java.lang.String")
        usuario.complete_task_as_self(pendiente["id"])
    except (BonitaError, requests.RequestException) as exc:
        raise CicloError("No se pudo avanzar el caso en Bonita; probá de nuevo en un momento.", 502) from exc


def _completar_en_bonita_como_admin(settings: Settings, case_id: int | None, tarea: str) -> None:
    """Completa la tarea con el usuario administrador de Bonita (para tareas que la app cierra sola)."""
    if case_id is None:
        raise CicloError("La emergencia no tiene caso en Bonita.", 409)
    try:
        admin = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
        admin.login(settings.bonita_username, settings.bonita_password)
        pendiente = admin.wait_for_task(case_id, tarea)
        if pendiente is None:
            raise CicloError(f"El caso {case_id} no está esperando la tarea '{tarea}' en Bonita.", 409)
        admin.complete_task_as_self(pendiente["id"])
    except (BonitaError, requests.RequestException) as exc:
        raise CicloError("No se pudo avanzar el caso en Bonita; probá de nuevo en un momento.", 502) from exc


def _retirar_ofertas(db: Session, emergencia: Emergencia) -> None:
    """Retira las ofertas de la ronda (versión nueva sin ítems): el historial queda."""
    ofertas = db.scalars(select(Oferta).where(Oferta.emergencia_id == emergencia.id).options(selectinload(Oferta.items)))
    for o in ofertas:
        if any(i.version == o.version_actual for i in o.items):
            o.version_actual += 1


def decidir(db: Session, settings: Settings, nacional: NacionalClient, *, emergencia: Emergencia,
            coordinador: Usuario, decision: str) -> None:
    """El Coordinador decide con la cobertura incompleta: PARCIAL sigue con lo reservado; REFORMULAR libera las
    reservas de la ronda, retira las ofertas, sube la ronda y vuelve a REGISTRADA para cargar lotes y publicar de nuevo.

    Lanza NacionalError si la API Nacional no responde (no se cambia nada)."""
    ev = _evaluacion(emergencia)
    if emergencia.estado is not EstadoEmergencia.EN_EVALUACION or ev is None:
        raise CicloError("La emergencia no está esperando una decisión del Coordinador.")
    if ev.cobertura_completa:
        raise CicloError("La cobertura está completa: no hay nada que decidir, el Municipio adjudica.")

    if decision == "REFORMULAR":
        # Primero lo que se puede repetir sin riesgo: si algo falla, el Coordinador reintenta y nada quedó a medias.
        for o in ev.ongs:
            if o.referencia:
                nacional.liberar(o.referencia)
    _completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_EVALUAR, coordinador.username,
                         {"decisionCoordinador": decision})

    if decision == "PARCIAL":
        emergencia.estado = EstadoEmergencia.ADJUDICACION
    else:
        _retirar_ofertas(db, emergencia)
        emergencia.ronda += 1
        emergencia.estado = EstadoEmergencia.REGISTRADA
        emergencia.evaluacion = None
        emergencia.ventana_ofertas_fin = None
    db.commit()


def adjudicar(settings: Settings, *, emergencia: Emergencia, municipal: Usuario, cuits: list[str]) -> None:
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
    _completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_ADJUDICAR, municipal.username,
                         {"ongsAdjudicadas": json.dumps(cuits)})


def monitorear(db: Session, settings: Settings, *, emergencia: Emergencia, coordinador: Usuario) -> None:
    """El Coordinador completa "Monitorear Ejecucion del Despliegue": habilita que las ONGs finalicen.
    Idempotente si Bonita ya avanzó (la tarea puede no estar pendiente)."""
    if emergencia.estado is not EstadoEmergencia.EN_EJECUCION:
        raise CicloError("La emergencia no está en ejecución.")
    if emergencia.monitoreo_completado:
        return  # ya hecho, idempotente
    _completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_MONITOREAR, coordinador.username, {})
    emergencia.monitoreo_completado = True
    db.commit()


def _ofertas_adjudicadas(db: Session, emergencia: Emergencia) -> list[Oferta]:
    return db.scalars(
        select(Oferta)
        .where(Oferta.emergencia_id == emergencia.id, Oferta.estado == EstadoOferta.ADJUDICADA)
        .options(selectinload(Oferta.ong))
    ).all()


def _todas_finalizadas(db: Session, emergencia: Emergencia) -> bool:
    adjudicadas = db.scalars(
        select(Oferta).where(Oferta.emergencia_id == emergencia.id, Oferta.estado.in_(
            [EstadoOferta.ADJUDICADA, EstadoOferta.FINALIZADA]
        ))
    ).all()
    return bool(adjudicadas) and all(o.estado is EstadoOferta.FINALIZADA for o in adjudicadas)


def finalizar_oferta(db: Session, settings: Settings, *, emergencia: Emergencia, ong: Ong) -> None:
    """La ONG informa que terminó sus actividades: oferta → FINALIZADA.
    Si todas las ONGs adjudicadas finalizaron, la app completa "Confirmar Finalizacion de Actividades" en Bonita."""
    if emergencia.estado is not EstadoEmergencia.EN_EJECUCION:
        raise CicloError("La emergencia no está en ejecución.")
    if not emergencia.monitoreo_completado:
        raise CicloError("El coordinador todavía no completó el monitoreo.", 409)
    oferta = db.scalar(
        select(Oferta).where(
            Oferta.emergencia_id == emergencia.id,
            Oferta.ong_id == ong.id,
            Oferta.estado.in_([EstadoOferta.ADJUDICADA, EstadoOferta.FINALIZADA]),
        )
    )
    if oferta is None:
        raise CicloError("No tenés una oferta adjudicada en esta emergencia.", 409)
    if oferta.estado is EstadoOferta.FINALIZADA:
        return  # idempotente
    oferta.estado = EstadoOferta.FINALIZADA
    db.flush()
    # Bonita: si todas finalizaron, completar "Confirmar Finalizacion de Actividades" una sola vez.
    # Versión simple: tarea común completada por el admin de la app.
    if _todas_finalizadas(db, emergencia):
        _completar_en_bonita_como_admin(settings, emergencia.bonita_case_id, TAREA_CONFIRMAR)
    db.commit()


def validar_cierre(db: Session, settings: Settings, *, emergencia: Emergencia, coordinador: Usuario) -> None:
    """El Coordinador valida el cierre bilateral. Solo posible cuando todas las ONGs adjudicadas finalizaron.
    Completa "Validar Cierre Operativo Bilateral": Bonita libera el stock y manda el evento CIERRE."""
    if emergencia.estado is not EstadoEmergencia.EN_EJECUCION:
        raise CicloError("La emergencia no está en ejecución.")
    if not _todas_finalizadas(db, emergencia):
        raise CicloError(
            "No se puede validar el cierre: alguna ONG adjudicada todavía no marcó sus actividades como finalizadas.",
            409,
        )
    _completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_VALIDAR, coordinador.username, {})
    # No se pasa a RESUELTA acá: eso lo hace el evento CIERRE que manda Bonita.
    db.commit()
