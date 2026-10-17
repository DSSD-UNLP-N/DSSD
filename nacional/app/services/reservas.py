"""Evaluación y reserva (eslabón 4, directiva 4), confirmación (eslabón 6) y liberación.

Al vencer la ventana, Bonita manda las ofertas consolidadas. Por cada ONG se calcula con qué nivel de
competencia opera y se RESERVA lo que ofreció (estado RESERVADA) hasta que se decida: lo elegido pasa a
ADJUDICADA (`confirmar`) y lo demás vuelve al inventario (`liberar`). Cada reserva se identifica por su
referencia `emg-{emergencia}-r{ronda}-{cuit}`, así que repetir una llamada no reserva dos veces.

La oferta de una ONG es una unidad y no se edita: si no alcanza el stock para algo de lo que ofreció, no se reserva
nada de esa oferta (NO_RESERVADA) y la ONG tiene que rehacerla; nunca se recorta.

Concurrencia: las filas de inventario involucradas se bloquean juntas y ordenadas por id (sin deadlocks) antes
de leer lo disponible. SQLite ignora el bloqueo, y ahí no hace falta.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Adjudicacion, AdjudicacionItem, EstadoAdjudicacion, EstadoOng, Inventario, Ong, OngCertificacion, TipoRecurso,
)
from app.schemas import (
    EvaluacionIn, EvaluacionOut, ItemEvaluadoOut, LiberacionOut, LoteCoberturaOut, OngEvaluadaOut, RecursoLiberadoOut,
)
from app.services.validacion import TipoRecursoDesconocido, competencia

VIGENTES = (EstadoAdjudicacion.RESERVADA, EstadoAdjudicacion.ADJUDICADA)


class ReservaError(ValueError):
    """Pedido inválido (400)."""


class ReservaNoExiste(LookupError):
    """La referencia no existe (404)."""


class ReservaEnConflicto(RuntimeError):
    """La reserva ya está en un estado que no admite esa operación (409)."""


def referencia(emergencia_id: int, ronda: int, cuit: str) -> str:
    return f"emg-{emergencia_id}-r{ronda}-{cuit}"


def _adjudicaciones(db: Session, referencias: list[str]) -> dict[str, Adjudicacion]:
    filas = db.scalars(
        select(Adjudicacion)
        .where(Adjudicacion.referencia_id.in_(referencias))
        .options(selectinload(Adjudicacion.items).selectinload(AdjudicacionItem.inventario).selectinload(
            Inventario.tipo_recurso))
    )
    return {a.referencia_id: a for a in filas}


def _bloquear_inventario(db: Session, ong_ids: set[int], tipo_ids: set[int]) -> dict[tuple[int, int], Inventario]:
    """Las filas (ONG, recurso) bloqueadas y releídas, ordenadas por id: lo disponible que se lee es el real."""
    if not ong_ids or not tipo_ids:
        return {}
    filas = db.scalars(
        select(Inventario)
        .where(Inventario.ong_id.in_(ong_ids), Inventario.tipo_recurso_id.in_(tipo_ids))
        .order_by(Inventario.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {(f.ong_id, f.tipo_recurso_id): f for f in filas}


def evaluar(db: Session, body: EvaluacionIn, hoy: date) -> EvaluacionOut:
    cuits = [o.cuit for o in body.ofertas]
    if len(set(cuits)) != len(cuits):
        raise ReservaError("Hay ONGs repetidas en las ofertas")
    for o in body.ofertas:
        lotes_de_oferta = [i.lote_id for i in o.items]
        if len(set(lotes_de_oferta)) != len(lotes_de_oferta):
            raise ReservaError(f"La oferta de {o.cuit} repite un lote")

    codigos = {i.tipo_recurso for o in body.ofertas for i in o.items}
    tipos = {
        t.codigo: t
        for t in db.scalars(
            select(TipoRecurso).where(TipoRecurso.codigo.in_(codigos)).options(selectinload(TipoRecurso.certificacion))
        )
    }
    desconocidos = sorted(codigos - tipos.keys())
    if desconocidos:
        raise TipoRecursoDesconocido(f"Tipo de recurso inexistente: {', '.join(desconocidos)}")

    ongs = {
        o.cuit: o
        for o in db.scalars(
            select(Ong).where(Ong.cuit.in_(cuits)).options(
                selectinload(Ong.certificaciones).selectinload(OngCertificacion.certificacion)
            )
        )
    }
    filas = _bloquear_inventario(db, {o.id for o in ongs.values()}, {t.id for t in tipos.values()})
    refs = {c: referencia(body.emergencia_id, body.ronda, c) for c in cuits}
    existentes = _adjudicaciones(db, list(refs.values()))
    for ref, adj in existentes.items():
        if adj.estado not in VIGENTES:
            raise ReservaEnConflicto(f"La referencia {ref} ya está {adj.estado.value}; no se puede evaluar de nuevo")

    ahora = datetime.now(timezone.utc)
    reservado_por_lote: dict[int, int] = defaultdict(int)
    salida: list[OngEvaluadaOut] = []
    for oferta in body.ofertas:
        ong, ref = ongs.get(oferta.cuit), refs[oferta.cuit]
        adj = existentes.get(ref)
        if adj is None:
            motivos = _no_alcanza(ong, oferta, tipos, filas)
            if motivos:
                salida.append(_sin_reserva(ong, oferta, tipos, body, hoy, motivos))
                continue
            adj = _reservar(ong, oferta, tipos, filas, ref, body.emergencia_id, ahora)
            db.add(adj)
        items = []
        for it in oferta.items:
            reservado_por_lote[it.lote_id] += it.cantidad
            nivel, riesgo, asignacion, obs = competencia(ong, tipos[it.tipo_recurso], body.gravedad, hoy)
            items.append(ItemEvaluadoOut(
                lote_id=it.lote_id, tipo_recurso=it.tipo_recurso, ofrecido=it.cantidad, reservado=it.cantidad,
                nivel=nivel, riesgo_permitido=riesgo, asignacion_sugerida=asignacion, observaciones=obs,
            ))
        salida.append(OngEvaluadaOut(cuit=ong.cuit, ong=ong.nombre, referencia=ref, estado=adj.estado.value,
                                     items=items))
    db.commit()

    lotes = []
    for lote in body.lotes:
        reservado = reservado_por_lote[lote.lote_id]
        lotes.append(LoteCoberturaOut(
            lote_id=lote.lote_id, tipo_recurso=lote.tipo_recurso, pedido=lote.cantidad, reservado=reservado,
            porcentaje=round(min(reservado, lote.cantidad) / lote.cantidad * 100, 1),
            cubierto=reservado >= lote.cantidad,
        ))
    return EvaluacionOut(
        emergencia_id=body.emergencia_id, ronda=body.ronda,
        cobertura_completa=bool(lotes) and all(l.cubierto for l in lotes),
        porcentaje_cobertura=round(sum(l.porcentaje for l in lotes) / len(lotes), 1) if lotes else 0.0,
        lotes=lotes, ongs=salida,
    )


def _por_recurso(oferta) -> dict[str, int]:
    ofrecido: dict[str, int] = defaultdict(int)
    for it in oferta.items:
        ofrecido[it.tipo_recurso] += it.cantidad
    return ofrecido


def _no_alcanza(ong, oferta, tipos, filas) -> list[str]:
    """Por qué no se puede reservar esta oferta entera (vacío = se puede). Se suma por recurso entre lotes."""
    if ong is None:
        return ["ONG no registrada en el Sistema Nacional"]
    motivos = []
    for codigo, cantidad in _por_recurso(oferta).items():
        fila = filas.get((ong.id, tipos[codigo].id))
        disponible = fila.disponible if fila is not None and ong.estado is EstadoOng.HABILITADA else 0
        if cantidad > disponible:
            motivos.append(f"{tipos[codigo].nombre}: ofrecida {cantidad} y disponible {disponible}")
    return motivos


def _reservar(ong, oferta, tipos, filas, ref, emergencia_id, ahora) -> Adjudicacion:
    """Bloquea todo lo ofrecido, sumado por recurso (ya se comprobó que alcanza)."""
    adj = Adjudicacion(referencia_id=ref, ong_id=ong.id, emergencia_id=emergencia_id, fecha_creacion=ahora,
                       estado=EstadoAdjudicacion.RESERVADA)
    for codigo, cantidad in _por_recurso(oferta).items():
        fila = filas[(ong.id, tipos[codigo].id)]
        fila.cantidad_comprometida += cantidad
        adj.items.append(AdjudicacionItem(inventario=fila, cantidad=cantidad))
    return adj


def _sin_reserva(ong, oferta, tipos, body, hoy, motivos) -> OngEvaluadaOut:
    """La oferta queda como llegó, sin reservar nada: la ONG tiene que rehacerla."""
    items = []
    for it in oferta.items:
        nivel, riesgo, asignacion, obs = competencia(ong, tipos[it.tipo_recurso], body.gravedad, hoy)
        items.append(ItemEvaluadoOut(
            lote_id=it.lote_id, tipo_recurso=it.tipo_recurso, ofrecido=it.cantidad, reservado=0,
            nivel=nivel, riesgo_permitido=riesgo, asignacion_sugerida=asignacion,
            observaciones=[f"Oferta sin reservar: {m}" for m in motivos] + obs,
        ))
    return OngEvaluadaOut(cuit=oferta.cuit, ong=ong.nombre if ong else None, referencia=None,
                          estado="NO_RESERVADA", items=items)


def _cargar_bloqueada(db: Session, ref: str) -> Adjudicacion:
    adj = db.scalar(
        select(Adjudicacion)
        .where(Adjudicacion.referencia_id == ref)
        .with_for_update()
        .options(selectinload(Adjudicacion.items).selectinload(AdjudicacionItem.inventario).selectinload(
            Inventario.tipo_recurso))
        .execution_options(populate_existing=True)
    )
    if adj is None:
        raise ReservaNoExiste(f"La referencia {ref} no existe")
    return adj


def confirmar(db: Session, ref: str) -> Adjudicacion:
    """RESERVADA -> ADJUDICADA. Repetirlo no cambia nada."""
    adj = _cargar_bloqueada(db, ref)
    if adj.estado in (EstadoAdjudicacion.LIBERADA, EstadoAdjudicacion.CERRADA):
        raise ReservaEnConflicto(f"La referencia {ref} está {adj.estado.value}; no se puede adjudicar")
    adj.estado = EstadoAdjudicacion.ADJUDICADA
    db.commit()
    return adj


def liberar(db: Session, ref: str) -> LiberacionOut:
    """RESERVADA o ADJUDICADA -> LIBERADA: devuelve el stock. Repetirlo no resta dos veces."""
    adj = _cargar_bloqueada(db, ref)
    if adj.estado is EstadoAdjudicacion.CERRADA:
        raise ReservaEnConflicto(f"La referencia {ref} ya está CERRADA; sus recursos ya se liberaron")
    if adj.estado is not EstadoAdjudicacion.LIBERADA:
        ids = sorted(i.inventario_id for i in adj.items)
        filas = db.scalars(
            select(Inventario).where(Inventario.id.in_(ids)).order_by(Inventario.id).with_for_update()
            .execution_options(populate_existing=True)
        ).all() if ids else []
        por_id = {f.id: f for f in filas}
        for it in adj.items:
            por_id[it.inventario_id].cantidad_comprometida -= it.cantidad
        adj.estado = EstadoAdjudicacion.LIBERADA
        db.commit()
    return LiberacionOut(
        referencia=ref, estado=adj.estado,
        liberado=[RecursoLiberadoOut(tipo_recurso=i.inventario.tipo_recurso.codigo, cantidad=i.cantidad)
                  for i in adj.items],
    )
