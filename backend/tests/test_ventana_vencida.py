"""Al vencer la ventana de ofertas, la emergencia pasa a CERRADA y ya no acepta ofertas."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Emergencia, EstadoEmergencia, Gravedad, Lote, Municipio, TipoLote
from app.services.emergencias import cerrar_ventanas_vencidas


def _convocatoria(seeded, fin):
    with seeded() as s:
        e = Emergencia(municipio_id=s.query(Municipio).one().id, tipo="terremoto", nivel_gravedad=Gravedad.ALTO,
                       zona_afectada="Centro", descripcion="x", bonita_case_id=1,
                       estado=EstadoEmergencia.CONVOCATORIA, ventana_ofertas_fin=fin)
        e.lotes = [Lote(recurso="Agua", cantidad=100, unidad="l", tipo=TipoLote.PRINCIPAL)]
        s.add(e)
        s.commit()
        return e.id, e.lotes[0].id


@pytest.fixture
def vencida(seeded):
    return _convocatoria(seeded, datetime.now(timezone.utc) - timedelta(minutes=5))


@pytest.fixture
def vigente(seeded):
    return _convocatoria(seeded, datetime.now(timezone.utc) + timedelta(hours=2))


def test_ventana_vencida_pasa_a_cerrada(login, vencida):
    r = login("coordinador.regional").get(f"/api/emergencias/{vencida[0]}")
    assert r.status_code == 200 and r.json()["estado"] == "CERRADA"


def test_ventana_vigente_sigue_abierta(login, vigente):
    r = login("coordinador.regional").get(f"/api/emergencias/{vigente[0]}")
    assert r.json()["estado"] == "CONVOCATORIA"


def test_listado_tambien_la_cierra(login, vencida):
    estados = {e["id"]: e["estado"] for e in login("coordinador.regional").get("/api/emergencias").json()}
    assert estados[vencida[0]] == "CERRADA"


def test_la_ong_sigue_viendo_la_cerrada_pero_no_puede_ofertar(login, vencida):
    emergencia_id, lote_id = vencida
    ong = login("ong.cruzroja")
    assert ong.get(f"/api/emergencias/{emergencia_id}").json()["estado"] == "CERRADA"
    r = ong.post(f"/api/emergencias/{emergencia_id}/ofertas",
                 json={"items": [{"lote_id": lote_id, "recurso": "Agua", "cantidad": 10}]})
    assert r.status_code == 400 and "cerró" in r.json()["detail"]


def test_cerrar_ventanas_no_pisa_la_evaluacion_que_empezo_mientras_tanto(seeded, vencida):
    """Justo al vencer, Bonita pide el consolidado (la emergencia pasa a EN_EVALUACION) a la vez que otra consulta cierra
    la ventana: la consulta que ya había leído CONVOCATORIA no puede volver la emergencia a CERRADA."""
    emergencia_id = vencida[0]
    with seeded() as consulta, seeded() as bonita:
        leer = consulta.scalars

        def leer_y_que_bonita_evalue(*args, **kwargs):
            leidas = list(leer(*args, **kwargs))  # la consulta ya vio la emergencia en CONVOCATORIA...
            e = bonita.get(Emergencia, emergencia_id)
            e.estado = EstadoEmergencia.EN_EVALUACION  # ...Bonita la pasa a EN_EVALUACION...
            bonita.commit()
            return iter(leidas)

        consulta.scalars = leer_y_que_bonita_evalue
        cerrar_ventanas_vencidas(consulta)  # ...y recién ahora la consulta intenta cerrarla
    with seeded() as s:
        assert s.get(Emergencia, emergencia_id).estado is EstadoEmergencia.EN_EVALUACION
