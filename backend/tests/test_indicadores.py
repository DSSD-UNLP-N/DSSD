"""Métricas del dashboard (servicio, sin HTTP): una función por bloque."""
import json
from datetime import date, datetime, timezone

import requests

from app.models import (
    Consorcio, ConsorcioMiembro, Emergencia, EstadoEmergencia, Gravedad, EstadoMiembro, EstadoOferta, Lote, Municipio, Oferta,
    OfertaItem, Ong,
)
from app.schemas.indicadores import Filtros
from app.services import indicadores

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
OCT = Filtros(desde=date(2026, 10, 1), hasta=date(2026, 10, 31), municipio_id=None)


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _municipio(db, nombre="Pilar"):
    m = Municipio(nombre=nombre, provincia="Buenos Aires")
    db.add(m)
    db.flush()
    return m


def _emergencia(db, municipio, estado=EstadoEmergencia.REGISTRADA, creada=None, **kw):
    e = Emergencia(municipio_id=municipio.id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO, zona_afectada="Centro",
                   descripcion="d", estado=estado, creada_en=creada or _utc(2026, 10, 10, 12), **kw)
    db.add(e)
    db.flush()
    return e


def _ong(db, nombre, cuit):
    o = Ong(nombre=nombre, cuit=cuit)
    db.add(o)
    db.flush()
    return o


def _lote(db, e, tipo_recurso="RACION_ALIMENTO"):
    lote = Lote(emergencia_id=e.id, recurso="Raciones", cantidad=100, unidad="raciones", tipo_recurso=tipo_recurso)
    db.add(lote)
    db.flush()
    return lote


def _oferta(db, e, ong, lote, cantidad=10, estado=EstadoOferta.ADJUDICADA, adjudicada=_utc(2026, 10, 15, 12)):
    o = Oferta(emergencia_id=e.id, ong_id=ong.id, estado=estado, adjudicada_en=adjudicada)
    db.add(o)
    db.flush()
    db.add(OfertaItem(oferta_id=o.id, version=1, lote_id=lote.id, recurso="Raciones", cantidad=cantidad))
    db.flush()
    return o


def _consorcio(db, e, lider, otra):
    c = Consorcio(emergencia_id=e.id, nombre="Unidas", ong_lider_id=lider.id)
    db.add(c)
    db.flush()
    for ong in (lider, otra):
        db.add(ConsorcioMiembro(consorcio_id=c.id, ong_id=ong.id, estado=EstadoMiembro.ACEPTADA,
                                invitado_por_ong_id=lider.id))
    db.flush()
    return c


def test_kpis_cuenta_por_estado_y_filtra_por_municipio(db):
    pilar, tigre = _municipio(db), _municipio(db, "Tigre")
    _emergencia(db, pilar, EstadoEmergencia.RESUELTA)
    _emergencia(db, pilar, EstadoEmergencia.EN_EJECUCION)
    _emergencia(db, tigre, EstadoEmergencia.REGISTRADA)
    _emergencia(db, pilar, EstadoEmergencia.RESUELTA, creada=_utc(2026, 9, 1))  # fuera del período
    db.commit()
    k = indicadores.kpis(db, OCT)
    assert (k.emergencias, k.resueltas, k.en_curso) == (3, 1, 2)
    k = indicadores.kpis(db, OCT.model_copy(update={"municipio_id": pilar.id}))
    assert (k.emergencias, k.resueltas, k.en_curso) == (2, 1, 1)


def test_kpis_el_rango_usa_la_hora_de_argentina(db):
    m = _municipio(db)
    _emergencia(db, m, creada=_utc(2026, 11, 1, 2, 30))  # 31/10 23:30 en Argentina: entra en octubre
    _emergencia(db, m, creada=_utc(2026, 10, 1, 2, 30))  # 30/9 23:30 en Argentina: no entra
    db.commit()
    assert indicadores.kpis(db, OCT).emergencias == 1


def test_cobertura_promedio_solo_de_las_evaluadas(db):
    m = _municipio(db)
    _emergencia(db, m, evaluacion=json.dumps({"porcentaje_cobertura": 80}))
    _emergencia(db, m, evaluacion=json.dumps({"porcentaje_cobertura": 55}))
    _emergencia(db, m)
    db.commit()
    assert indicadores.kpis(db, OCT).cobertura_promedio == 67.5


def test_pct_consorcio(db):
    m = _municipio(db)
    a, b = _ong(db, "A", "30-1"), _ong(db, "B", "30-2")
    e1 = _emergencia(db, m, EstadoEmergencia.RESUELTA)
    _emergencia(db, m, EstadoEmergencia.RESUELTA)
    _consorcio(db, e1, a, b)
    _oferta(db, e1, b, _lote(db, e1))
    db.commit()
    assert indicadores.kpis(db, OCT).pct_consorcio == 50.0


def test_pct_consorcio_sin_resueltas_es_none(db):
    m = _municipio(db)
    _emergencia(db, m, EstadoEmergencia.EN_EJECUCION)
    db.commit()
    k = indicadores.kpis(db, OCT)
    assert k.pct_consorcio is None and k.cobertura_promedio is None


def test_suministros_por_mes_y_tipo_usa_version_vigente(db):
    m = _municipio(db)
    a, b, c = _ong(db, "A", "30-1"), _ong(db, "B", "30-2"), _ong(db, "C", "30-3")
    e = _emergencia(db, m)
    raciones, agua = _lote(db, e), _lote(db, e, None)
    o = _oferta(db, e, a, raciones, cantidad=10)  # v1 (ya no vigente)
    db.add(OfertaItem(oferta_id=o.id, version=2, lote_id=raciones.id, recurso="Raciones", cantidad=30))
    db.add(OfertaItem(oferta_id=o.id, version=2, lote_id=agua.id, recurso="Agua", cantidad=5))
    o.version_actual = 2
    _oferta(db, e, b, raciones, cantidad=7, estado=EstadoOferta.FINALIZADA, adjudicada=_utc(2026, 10, 20))
    _oferta(db, e, c, raciones, cantidad=4, adjudicada=_utc(2026, 11, 20))  # otro mes: fuera del filtro
    db.commit()
    s = indicadores.suministros_por_mes(db, OCT)
    assert [(x.mes, x.tipo_recurso, x.cantidad) for x in s] == [
        ("2026-10", "RACION_ALIMENTO", 37), ("2026-10", "Sin tipo", 5),
    ]


def test_suministros_ignora_ofertas_sin_adjudicada_en(db):
    m = _municipio(db)
    a, b = _ong(db, "A", "30-1"), _ong(db, "B", "30-2")
    e = _emergencia(db, m)
    lote = _lote(db, e)
    _oferta(db, e, a, lote, adjudicada=None)
    _oferta(db, e, b, lote, estado=EstadoOferta.PRESENTADA)
    db.commit()
    assert indicadores.suministros_por_mes(db, OCT) == []


def test_suministros_filtra_por_municipio_de_la_emergencia(db):
    pilar, tigre = _municipio(db), _municipio(db, "Tigre")
    a = _ong(db, "A", "30-1")
    e1, e2 = _emergencia(db, pilar), _emergencia(db, tigre)
    _oferta(db, e1, a, _lote(db, e1), cantidad=3)
    _oferta(db, e2, a, _lote(db, e2), cantidad=9)
    db.commit()
    s = indicadores.suministros_por_mes(db, OCT.model_copy(update={"municipio_id": tigre.id}))
    assert [x.cantidad for x in s] == [9]


def test_emergencias_por_estado_incluye_todos_los_estados_con_cero(db):
    m = _municipio(db)
    _emergencia(db, m, EstadoEmergencia.CONVOCATORIA)
    db.commit()
    r = indicadores.emergencias_por_estado(db, OCT)
    assert [x.estado for x in r] == [e.value for e in EstadoEmergencia]
    por = {x.estado: x for x in r}
    assert por["CONVOCATORIA"].cantidad == 1 and por["CONVOCATORIA"].etiqueta == "Convocatoria abierta"
    assert por["RESUELTA"].cantidad == 0 and por["RESUELTA"].etiqueta == "Resuelta"


def _nodo(nombre, listo, archivado, tipo="USER_TASK", estado="ready"):
    return {"type": tipo, "name": nombre, "state": estado, "reached_state_date": listo, "archivedDate": archivado}


def _con_caso(db, caso, **kw):
    e = _emergencia(db, _municipio(db, f"M{caso}"), bonita_case_id=caso, **kw)
    return e


def test_tiempos_promedio_por_etapa_en_orden(db, fake_bonita):
    _con_caso(db, 1)
    _con_caso(db, 2)
    fake_bonita.nodos["1"] = [
        _nodo(ETAPAS[2], "2026-11-08 10:00:00.000", "2026-11-08 14:00:00.000"),  # 4 h
        _nodo(ETAPAS[0], "2026-11-08 08:00:00.000", "2026-11-08 09:00:00.000"),  # 1 h
        _nodo(ETAPAS[0], "2026-11-08 08:00:00.000", "2026-11-08 08:00:00.100", estado="completed"),  # se ignora
        _nodo("Tarea de servicio", "2026-11-08 08:00:00.000", "2026-11-08 20:00:00.000", tipo="AUTOMATIC_TASK"),
        _nodo("Otra tarea humana", "2026-11-08 08:00:00.000", "2026-11-08 20:00:00.000"),  # fuera de la lista
    ]
    fake_bonita.nodos["2"] = [_nodo(ETAPAS[2], "2026-11-08 10:00:00.000", "2026-11-08 12:30:00.000")]  # 2,5 h
    t = indicadores.tiempos_por_etapa(db, fake_bonita, OCT)
    assert t.disponible and t.motivo is None
    assert [(x.tarea, x.horas_promedio, x.emergencias) for x in t.etapas] == [
        (ETAPAS[0], 1.0, 1), (ETAPAS[2], 3.25, 2),
    ]


def test_etapas_repetidas_se_suman_por_emergencia(db, fake_bonita):
    _con_caso(db, 1)
    _con_caso(db, 2)
    fake_bonita.nodos["1"] = [  # dos rondas: 2 h + 4 h = 6 h en la emergencia
        _nodo(ETAPAS[3], "2026-11-08 10:00:00.000", "2026-11-08 12:00:00.000"),
        _nodo(ETAPAS[3], "2026-11-08 15:00:00.000", "2026-11-08 19:00:00.000"),
    ]
    fake_bonita.nodos["2"] = [_nodo(ETAPAS[3], "2026-11-08 10:00:00", "2026-11-08 12:00:00")]  # 2 h
    t = indicadores.tiempos_por_etapa(db, fake_bonita, OCT)
    assert [(x.horas_promedio, x.emergencias) for x in t.etapas] == [(4.0, 2)]


def test_caso_inexistente_se_saltea(db, fake_bonita):
    _con_caso(db, 1)
    _con_caso(db, 2)
    fake_bonita.nodos["2"] = [_nodo(ETAPAS[4], "2026-11-08 10:00:00.000", "2026-11-08 11:00:00.000")]
    original = fake_bonita.get_archived_flow_nodes

    def con_404(case_id):
        if case_id == "1":
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError("404", response=resp)
        return original(case_id)

    fake_bonita.get_archived_flow_nodes = con_404
    t = indicadores.tiempos_por_etapa(db, fake_bonita, OCT)
    assert t.disponible and [(x.tarea, x.emergencias) for x in t.etapas] == [(ETAPAS[4], 1)]


def test_horas_total_promedio_de_las_resueltas(db, fake_bonita):
    m = _municipio(db)
    _emergencia(db, m, EstadoEmergencia.RESUELTA, creada=_utc(2026, 10, 10, 0), cierre_validado_en=_utc(2026, 10, 10, 10))
    _emergencia(db, m, EstadoEmergencia.RESUELTA, creada=_utc(2026, 10, 11, 0), cierre_validado_en=_utc(2026, 10, 11, 5))
    _emergencia(db, m, EstadoEmergencia.EN_EJECUCION)
    db.commit()
    assert indicadores.tiempos_por_etapa(db, fake_bonita, OCT).horas_total_promedio == 7.5


def test_finalizadas_lista_ongs_y_consorcio(db):
    m = _municipio(db)
    a, b, c = _ong(db, "Beta", "30-1"), _ong(db, "Alfa", "30-2"), _ong(db, "Gama", "30-3")
    e = _emergencia(db, m, EstadoEmergencia.RESUELTA, creada=_utc(2026, 10, 10, 0),
                    cierre_validado_en=_utc(2026, 10, 11, 12), evaluacion=json.dumps({"porcentaje_cobertura": 92.46}))
    _emergencia(db, m, EstadoEmergencia.EN_EJECUCION)
    lote = _lote(db, e)
    _consorcio(db, e, a, b)
    _oferta(db, e, a, lote)
    _oferta(db, e, b, lote, estado=EstadoOferta.FINALIZADA)
    _oferta(db, e, c, lote, estado=EstadoOferta.NO_ADJUDICADA, adjudicada=None)
    db.commit()
    f = indicadores.finalizadas(db, OCT)
    assert len(f) == 1
    assert (f[0].emergencia_id, f[0].municipio, f[0].tipo, f[0].gravedad) == (e.id, "Pilar", "Inundación", "ALTO")
    assert f[0].ongs == ["Alfa", "Beta"]
    assert f[0].consorcio is True
    assert (f[0].horas_total, f[0].cobertura) == (36.0, 92.5)


def test_reporte_vacio(db, fake_bonita):
    r = indicadores.reporte(db, fake_bonita, OCT)
    assert (r.kpis.emergencias, r.kpis.pct_consorcio, r.kpis.cobertura_promedio) == (0, None, None)
    assert r.suministros == [] and r.finalizadas == []
    assert len(r.estados) == len(EstadoEmergencia) and all(x.cantidad == 0 for x in r.estados)
    assert r.tiempos.disponible and r.tiempos.etapas == [] and r.tiempos.horas_total_promedio is None
    assert r.filtros == OCT and r.generado_en.tzinfo is not None


def test_reporte_con_bonita_caido_marca_tiempos_no_disponible(db, fake_bonita):
    m = _municipio(db)
    _emergencia(db, m, EstadoEmergencia.RESUELTA, bonita_case_id=1, creada=_utc(2026, 10, 10, 0),
                cierre_validado_en=_utc(2026, 10, 10, 6))
    db.commit()
    fake_bonita.falla = True
    r = indicadores.reporte(db, fake_bonita, OCT)
    assert r.kpis.resueltas == 1
    assert not r.tiempos.disponible and r.tiempos.motivo and r.tiempos.etapas == []
    assert r.tiempos.horas_total_promedio == 6.0


def test_reporte_sin_bonita_configurado(db):
    r = indicadores.reporte(db, None, OCT)
    assert not r.tiempos.disponible and r.tiempos.motivo == "Bonita no configurado"
