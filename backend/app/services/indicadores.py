"""Métricas del dashboard de indicadores: una función por bloque, todas con los mismos `Filtros`.

El rango de fechas se aplica sobre `creada_en` de la emergencia (suministros usa `adjudicada_en` de la oferta), en la
hora de Argentina. Tiempos por etapa, cursos de acción y casos cruzan la base con Bonita; el resto sale solo de la base.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.labels import ESTADO_LABEL, TIPO_LABEL
from app.integrations.bonita import BonitaError
from app.models import Emergencia, EstadoEmergencia, EstadoOferta, Lote, Oferta, OfertaItem
from app.schemas.indicadores import (
    Casos, CursoAccion, Cursos, EstadoCantidad, Filtros, Finalizada, Kpis, Reporte, SuministroMes, TiempoEtapa, Tiempos,
)
from app.services.consorcios import consorcios_validos, miembros_aceptados

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
SIN_TIPO = "Sin tipo"
ETAPAS = [
    "Revisar Informacion y Generar Lotes de Necesidades",
    "Publicar Convocatoria y Notificar a la Red de ONGs",
    "Cargar Ofertas de Ayuda",
    "Evaluar Cobertura y Definir Curso de Accion",
    "Adjudicar Ofertas",
    "Monitorear Ejecucion del Despliegue",
    "Confirmar Finalizacion de Actividades",
    "Validar Cierre Operativo Bilateral",
]
_ADJUDICADAS = (EstadoOferta.ADJUDICADA, EstadoOferta.FINALIZADA)
REVISAR, PUBLICAR, EVALUAR, ADJUDICAR = ETAPAS[0], ETAPAS[1], ETAPAS[3], ETAPAS[4]
CURSOS = [
    ("TOTAL", "Cobertura total: directo a adjudicar"),
    ("PARCIAL", "Continuar con cobertura parcial"),
    ("REFORMULAR", "Reformular lotes"),
    ("REABRIR", "Reabrir convocatoria"),
]


def _utc(dt: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona: son UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _limites(f: Filtros) -> tuple[datetime, datetime]:
    """[desde 00:00, hasta 23:59:59.999] en Argentina, expresado en UTC."""
    ini = datetime.combine(f.desde, time.min, tzinfo=ZONA)
    fin = datetime.combine(f.hasta, time.max, tzinfo=ZONA).replace(microsecond=999000)
    return ini.astimezone(timezone.utc), fin.astimezone(timezone.utc)


def _emergencias(db: Session, f: Filtros) -> list[Emergencia]:
    ini, fin = _limites(f)
    q = select(Emergencia).where(Emergencia.creada_en >= ini, Emergencia.creada_en <= fin)
    if f.municipio_id is not None:
        q = q.where(Emergencia.municipio_id == f.municipio_id)
    return list(db.scalars(q.order_by(Emergencia.creada_en.desc(), Emergencia.id.desc()).options(
        selectinload(Emergencia.municipio))))


def _cobertura(e: Emergencia) -> float | None:
    if not e.evaluacion:
        return None
    try:
        valor = json.loads(e.evaluacion).get("porcentaje_cobertura")
    except (ValueError, AttributeError):
        return None
    return float(valor) if isinstance(valor, (int, float)) else None


def _promedio(valores: list[float], decimales: int) -> float | None:
    return round(sum(valores) / len(valores), decimales) if valores else None


def _ongs_adjudicadas(db: Session, emergencia_id: int) -> dict[int, str]:
    filas = db.scalars(
        select(Oferta).where(Oferta.emergencia_id == emergencia_id, Oferta.estado.in_(_ADJUDICADAS))
        .options(selectinload(Oferta.ong))
    )
    return {o.ong_id: o.ong.nombre for o in filas}


def _hubo_consorcio(db: Session, emergencia_id: int) -> bool:
    """Un consorcio válido con al menos un miembro con oferta adjudicada o finalizada."""
    adjudicadas = _ongs_adjudicadas(db, emergencia_id)
    return any(
        m.ong_id in adjudicadas for c in consorcios_validos(db, emergencia_id) for m in miembros_aceptados(c)
    )


def _horas(e: Emergencia) -> float | None:
    if e.cierre_validado_en is None:
        return None
    return (_utc(e.cierre_validado_en) - _utc(e.creada_en)).total_seconds() / 3600


def kpis(db: Session, f: Filtros) -> Kpis:
    es = _emergencias(db, f)
    resueltas = [e for e in es if e.estado is EstadoEmergencia.RESUELTA]
    con_consorcio = sum(1 for e in resueltas if _hubo_consorcio(db, e.id))
    return Kpis(
        emergencias=len(es),
        resueltas=len(resueltas),
        en_curso=len(es) - len(resueltas),
        pct_consorcio=round(100 * con_consorcio / len(resueltas), 1) if resueltas else None,
        cobertura_promedio=_promedio([c for c in map(_cobertura, es) if c is not None], 1),
    )


def suministros_por_mes(db: Session, f: Filtros) -> list[SuministroMes]:
    ini, fin = _limites(f)
    q = (
        select(Oferta.adjudicada_en, Lote.tipo_recurso, OfertaItem.cantidad)
        .join(OfertaItem, (OfertaItem.oferta_id == Oferta.id) & (OfertaItem.version == Oferta.version_actual))
        .join(Lote, Lote.id == OfertaItem.lote_id)
        .join(Emergencia, Emergencia.id == Oferta.emergencia_id)
        .where(Oferta.estado.in_(_ADJUDICADAS), Oferta.adjudicada_en.is_not(None),
               Oferta.adjudicada_en >= ini, Oferta.adjudicada_en <= fin)
    )
    if f.municipio_id is not None:
        q = q.where(Emergencia.municipio_id == f.municipio_id)
    total: dict[tuple[str, str], int] = defaultdict(int)
    for cuando, tipo, cantidad in db.execute(q):
        mes = _utc(cuando).astimezone(ZONA).strftime("%Y-%m")
        total[(mes, tipo or SIN_TIPO)] += cantidad
    return [SuministroMes(mes=m, tipo_recurso=t, cantidad=c) for (m, t), c in sorted(total.items())]


def emergencias_por_estado(db: Session, f: Filtros) -> list[EstadoCantidad]:
    cuenta: dict[EstadoEmergencia, int] = defaultdict(int)
    for e in _emergencias(db, f):
        cuenta[e.estado] += 1
    return [
        EstadoCantidad(estado=s.value, etiqueta=ESTADO_LABEL.get(s.value, s.value), cantidad=cuenta[s])
        for s in EstadoEmergencia
    ]


def _fecha_bonita(texto: str) -> datetime:
    """'2026-11-08 21:54:53.794' (hora del servidor de Bonita, UTC)."""
    for formato in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(texto)


def _horas_por_tarea(nodos: list[dict]) -> dict[str, float]:
    """Horas que cada tarea humana (de la lista fija) estuvo lista, sumadas entre sus instancias."""
    total: dict[str, float] = defaultdict(float)
    for n in nodos:
        if n.get("type") != "USER_TASK" or n.get("state") != "ready" or n.get("name") not in ETAPAS:
            continue
        try:
            horas = (_fecha_bonita(n["archivedDate"]) - _fecha_bonita(n["reached_state_date"])) / timedelta(hours=1)
        except (KeyError, ValueError, TypeError):
            continue
        total[n["name"]] += horas
    return total


def _horas_total_promedio(db: Session, f: Filtros) -> float | None:
    horas = [_horas(e) for e in _emergencias(db, f) if e.estado is EstadoEmergencia.RESUELTA]
    return _promedio([h for h in horas if h is not None], 4)


def _es_404(exc: requests.HTTPError) -> bool:
    return exc.response is not None and exc.response.status_code == 404


def _nodos(bonita, emergencias: list[Emergencia]) -> dict[int, list[dict]]:
    """Historial de Bonita de cada emergencia con caso (id de emergencia -> nodos). Saltea los casos que Bonita no conoce
    (404) y deja subir los demás errores."""
    salida = {}
    for e in emergencias:
        if e.bonita_case_id is None:
            continue
        try:
            salida[e.id] = bonita.get_archived_flow_nodes(str(e.bonita_case_id))
        except requests.HTTPError as exc:
            if not _es_404(exc):
                raise
    return salida


def tiempos_por_etapa(db: Session, bonita, f: Filtros, nodos: dict[int, list[dict]] | None = None) -> Tiempos:
    """Promedio por tarea entre las emergencias que la tienen. Deja subir los errores de Bonita (salvo caso 404)."""
    if nodos is None:
        nodos = _nodos(bonita, _emergencias(db, f))
    por_tarea: dict[str, list[float]] = defaultdict(list)
    for historial in nodos.values():
        for tarea, horas in _horas_por_tarea(historial).items():
            por_tarea[tarea].append(horas)
    etapas = [
        TiempoEtapa(tarea=t, horas_promedio=_promedio(por_tarea[t], 4), emergencias=len(por_tarea[t]))
        for t in ETAPAS if por_tarea.get(t)
    ]
    return Tiempos(disponible=True, motivo=None, etapas=etapas, horas_total_promedio=_horas_total_promedio(db, f))


def _recorrido(nodos: list[dict]) -> Counter:
    """Cursos de acción que tomó un caso, deducidos de las tareas humanas que completó en Bonita: cada REFORMULAR vuelve
    a «Revisar», cada REABRIR vuelve a «Publicar» sin pasar por «Revisar», y el caso llega a «Adjudicar» con cobertura
    total (sin «Evaluar» en la última ronda) o porque el Coordinador eligió PARCIAL."""
    hechas = Counter(n.get("name") for n in nodos if n.get("type") == "USER_TASK" and n.get("state") == "completed")
    cursos = Counter(REFORMULAR=max(hechas[REVISAR] - 1, 0), REABRIR=max(hechas[PUBLICAR] - hechas[REVISAR], 0))
    if any(n.get("name") == ADJUDICAR for n in nodos):  # «Adjudicar» activada (pendiente o hecha)
        cursos["PARCIAL" if hechas[EVALUAR] > cursos["REFORMULAR"] + cursos["REABRIR"] else "TOTAL"] = 1
    return +cursos  # sin los que quedaron en cero


def cursos_de_accion(db: Session, bonita, f: Filtros, nodos: dict[int, list[dict]] | None = None) -> Cursos:
    """Por cuál de los cursos de acción pasó cada emergencia (Bonita) y con qué cobertura terminó (base de la app)."""
    es = {e.id: e for e in _emergencias(db, f)}
    if nodos is None:
        nodos = _nodos(bonita, list(es.values()))
    emergencias: dict[str, list[Emergencia]] = defaultdict(list)
    veces: Counter = Counter()
    for emergencia_id, historial in nodos.items():
        for curso, n in _recorrido(historial).items():
            emergencias[curso].append(es[emergencia_id])
            veces[curso] += n
    filas = [
        CursoAccion(curso=c, etiqueta=etiqueta, emergencias=len(emergencias[c]), veces=veces[c],
                    cobertura_promedio=_promedio([x for x in map(_cobertura, emergencias[c]) if x is not None], 1))
        for c, etiqueta in CURSOS
    ]
    return Cursos(disponible=True, motivo=None, filas=filas)


def _caso(bonita, case_id: int) -> tuple[bool, dict | None]:
    """(abierto, caso archivado). Bonita contesta 404 por un caso que ya terminó; ahí se busca en los archivados."""
    try:
        bonita.get_case(str(case_id))
        return True, None
    except requests.HTTPError as exc:
        if not _es_404(exc):
            raise
    return False, bonita.get_archived_case(str(case_id))


def casos_en_bonita(db: Session, bonita, f: Filtros) -> Casos:
    """Si el caso de cada emergencia está abierto o archivado en Bonita y si eso coincide con la app (resuelta = caso
    archivado; cualquier otro estado = caso abierto). Promedia la duración de los casos archivados según el motor."""
    abiertos, archivados, consistentes = 0, 0, 0
    inconsistentes: list[int] = []
    horas: list[float] = []
    for e in _emergencias(db, f):
        if e.bonita_case_id is None:
            continue
        abierto, archivado = _caso(bonita, e.bonita_case_id)
        abiertos += abierto
        archivados += archivado is not None
        if archivado is not None:
            try:
                horas.append((_fecha_bonita(archivado["end_date"]) - _fecha_bonita(archivado["start"])) / timedelta(hours=1))
            except (KeyError, ValueError, TypeError):
                pass
        resuelta = e.estado is EstadoEmergencia.RESUELTA
        if (resuelta and archivado is not None) or (not resuelta and abierto):
            consistentes += 1
        else:
            inconsistentes.append(e.id)
    return Casos(disponible=True, motivo=None, abiertos=abiertos, archivados=archivados, consistentes=consistentes,
                 inconsistentes=inconsistentes, horas_resolucion_promedio=_promedio(horas, 4))


def finalizadas(db: Session, f: Filtros) -> list[Finalizada]:
    salida = []
    for e in _emergencias(db, f):
        if e.estado is not EstadoEmergencia.RESUELTA:
            continue
        horas, cobertura = _horas(e), _cobertura(e)
        salida.append(Finalizada(
            emergencia_id=e.id,
            municipio=e.municipio.nombre,
            tipo=TIPO_LABEL.get(e.tipo, e.tipo),
            gravedad=e.nivel_gravedad.value,
            ongs=sorted(_ongs_adjudicadas(db, e.id).values()),
            consorcio=_hubo_consorcio(db, e.id),
            horas_total=round(horas, 4) if horas is not None else None,
            cobertura=round(cobertura, 1) if cobertura is not None else None,
        ))
    return salida


def reporte(db: Session, bonita, f: Filtros) -> Reporte:
    motivo = "Bonita no responde: no se pudieron leer los datos del motor." if bonita is None else None
    if bonita is not None:
        try:
            nodos = _nodos(bonita, _emergencias(db, f))  # una sola lectura del historial para tiempos y cursos
            tiempos = tiempos_por_etapa(db, bonita, f, nodos)
            cursos = cursos_de_accion(db, bonita, f, nodos)
            casos = casos_en_bonita(db, bonita, f)
        except (requests.RequestException, BonitaError, ValueError):  # ValueError: Bonita no devolvió JSON
            motivo = "Bonita no disponible: no se pudieron leer los datos del motor."
    if motivo:
        tiempos = _tiempos_no_disponible(db, f, motivo)
        cursos = Cursos(disponible=False, motivo=motivo, filas=[])
        casos = Casos(disponible=False, motivo=motivo, abiertos=0, archivados=0, consistentes=0, inconsistentes=[],
                      horas_resolucion_promedio=None)
    return Reporte(
        filtros=f,
        generado_en=datetime.now(timezone.utc),
        kpis=kpis(db, f),
        suministros=suministros_por_mes(db, f),
        estados=emergencias_por_estado(db, f),
        tiempos=tiempos,
        cursos=cursos,
        casos=casos,
        finalizadas=finalizadas(db, f),
    )


def _tiempos_no_disponible(db: Session, f: Filtros, motivo: str) -> Tiempos:
    return Tiempos(disponible=False, motivo=motivo, etapas=[], horas_total_promedio=_horas_total_promedio(db, f))
