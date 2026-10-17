"""Después de adjudicar: el Coordinador monitorea, cada ONG marca su actividad como finalizada y el Coordinador valida el
cierre bilateral. Cada paso reemplaza a una tarea humana de Bonita (como en `ciclo.py`).

  Monitorear Ejecucion del Despliegue  -> Coordinador            (`monitorear`)
  Confirmar Finalizacion de Actividades -> ONG, versión simple:   una sola tarea, la completa la app cuando todas las
                                           ONGs adjudicadas finalizaron, con el usuario de la que finalizó última (`finalizar`)
  Validar Cierre Operativo Bilateral    -> Coordinador            (`validar_cierre`)

Lo que sigue (liberar en la API Nacional y avisar con el evento CIERRE) lo hace Bonita sola con su conector.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.models import Emergencia, EstadoEmergencia, EstadoOferta, Oferta, Rol, Usuario
from app.schemas.api import EjecucionOut, OngEjecucionOut
from app.services.ciclo import CicloError, completar_en_bonita

TAREA_MONITOREAR = "Monitorear Ejecucion"
TAREA_FINALIZAR = "Confirmar Finalizacion"
TAREA_VALIDAR = "Validar Cierre"

ADJUDICADAS = (EstadoOferta.ADJUDICADA, EstadoOferta.FINALIZADA)


def _adjudicadas(db: Session, emergencia: Emergencia) -> list[Oferta]:
    return list(db.scalars(
        select(Oferta)
        .where(Oferta.emergencia_id == emergencia.id, Oferta.estado.in_(ADJUDICADAS))
        .options(selectinload(Oferta.ong))
        .order_by(Oferta.id)
    ))


def _en_ejecucion(emergencia: Emergencia) -> None:
    if emergencia.estado is not EstadoEmergencia.EN_EJECUCION:
        raise CicloError("La emergencia no está en ejecución.")


def resumen(db: Session, emergencia: Emergencia, user: Usuario) -> EjecucionOut | None:
    """Cómo va la ejecución, o None si la emergencia todavía no se adjudicó. La ONG solo ve su propia fila."""
    if emergencia.estado not in (EstadoEmergencia.EN_EJECUCION, EstadoEmergencia.RESUELTA):
        return None
    ofertas = _adjudicadas(db, emergencia)
    filas = [o for o in ofertas if user.rol is not Rol.ONG or o.ong_id == user.ong_id]
    return EjecucionOut(
        monitoreo_iniciado=emergencia.monitoreo_iniciado_en is not None,
        cierre_validado=emergencia.cierre_validado_en is not None,
        todas_finalizadas=bool(ofertas) and all(o.estado is EstadoOferta.FINALIZADA for o in ofertas),
        ongs=[OngEjecucionOut(cuit=o.ong.cuit, nombre=o.ong.nombre, estado=o.estado) for o in filas],
    )


def monitorear(db: Session, settings: Settings, *, emergencia: Emergencia, coordinador: Usuario) -> None:
    """El Coordinador empieza a monitorear la ejecución: desde ahí las ONGs pueden marcar su actividad como finalizada."""
    _en_ejecucion(emergencia)
    if emergencia.monitoreo_iniciado_en is not None:
        raise CicloError("El monitoreo de la ejecución ya empezó.")
    completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_MONITOREAR, coordinador.username, {})
    emergencia.monitoreo_iniciado_en = datetime.now(timezone.utc)
    db.commit()


def finalizar(db: Session, settings: Settings, *, emergencia: Emergencia, usuario: Usuario) -> None:
    """Una ONG adjudicada informa que terminó su actividad. Cuando terminaron todas, la app completa "Confirmar
    Finalizacion" en Bonita y el Coordinador puede validar el cierre. Repetirlo no cambia nada.

    Si Bonita no puede avanzar, el llamador revierte: la oferta no queda marcada y la ONG reintenta."""
    _en_ejecucion(emergencia)
    if emergencia.monitoreo_iniciado_en is None:
        raise CicloError("El Coordinador todavía no empezó el monitoreo de la ejecución.")
    ofertas = _adjudicadas(db, emergencia)
    propia = next((o for o in ofertas if o.ong_id == usuario.ong_id), None)
    if propia is None:
        raise CicloError("Tu ONG no fue adjudicada en esta emergencia.", 403)
    if propia.estado is EstadoOferta.FINALIZADA:
        return
    propia.estado = EstadoOferta.FINALIZADA
    if all(o.estado is EstadoOferta.FINALIZADA for o in ofertas):
        completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_FINALIZAR, usuario.username, {})
    db.commit()


def validar_cierre(db: Session, settings: Settings, *, emergencia: Emergencia, coordinador: Usuario) -> None:
    """El Coordinador valida el cierre bilateral cuando todas las ONGs adjudicadas finalizaron. Bonita libera los
    recursos en la API Nacional y le avisa a la app con el evento CIERRE."""
    _en_ejecucion(emergencia)
    if emergencia.cierre_validado_en is not None:
        raise CicloError("El cierre ya fue validado; Bonita está liberando los recursos.")
    pendientes = [o.ong.nombre for o in _adjudicadas(db, emergencia) if o.estado is not EstadoOferta.FINALIZADA]
    if pendientes:
        raise CicloError(f"Faltan por finalizar: {', '.join(pendientes)}.")
    completar_en_bonita(settings, emergencia.bonita_case_id, TAREA_VALIDAR, coordinador.username, {})
    emergencia.cierre_validado_en = datetime.now(timezone.utc)
    db.commit()
