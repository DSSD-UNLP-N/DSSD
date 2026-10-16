"""GET /api/bonita/emergencias/{id}/ofertas: lo que Bonita le pide a la app al vencer la ventana."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Emergencia, EstadoEmergencia, Lote, Municipio, Oferta, OfertaItem, Ong,
)

from tests.conftest import PASSWORD

CLAVE = {"X-Api-Key": "rescuesync-dev-key"}
CRUZ_ROJA = "30-54666544-5"


def _sin_zona(delta):
    return datetime.now(timezone.utc).replace(tzinfo=None) + delta


@pytest.fixture
def vencida(seeded):
    """Emergencia con ventana vencida, 2 lotes (uno sin tipo) y la oferta de Cruz Roja en la versión 2."""
    with seeded() as s:
        e = Emergencia(municipio_id=s.query(Municipio).one().id, tipo="inundacion", nivel_gravedad="ALTO",
                       zona_afectada="Centro", descripcion="d", estado=EstadoEmergencia.CONVOCATORIA,
                       ventana_ofertas_fin=_sin_zona(-timedelta(minutes=1)))
        e.lotes = [Lote(recurso="Paramédicos", tipo_recurso="PARAMEDICO", cantidad=10, unidad="personas"),
                   Lote(recurso="Libre", tipo_recurso=None, cantidad=3, unidad="u")]
        s.add(e)
        s.flush()
        ong = s.query(Ong).filter_by(cuit=CRUZ_ROJA).one()
        o = Oferta(emergencia_id=e.id, ong_id=ong.id, version_actual=2)
        s.add(o)
        s.flush()
        pm, libre = e.lotes
        s.add_all([  # la versión 1 no tiene que salir; en la 2 el lote libre no se valida
            OfertaItem(oferta_id=o.id, version=1, lote_id=pm.id, recurso="p", cantidad=1),
            OfertaItem(oferta_id=o.id, version=2, lote_id=pm.id, recurso="p", cantidad=4),
            OfertaItem(oferta_id=o.id, version=2, lote_id=libre.id, recurso="l", cantidad=2),
        ])
        s.commit()
        return e.id, pm.id


def _estado(seeded, emergencia_id):
    with seeded() as s:
        return s.get(Emergencia, emergencia_id).estado


def test_sin_clave_o_con_clave_mala_es_401(client, vencida):
    url = f"/api/bonita/emergencias/{vencida[0]}/ofertas"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-Api-Key": "otra"}).status_code == 401


def test_devuelve_el_consolidado_del_contrato(client, vencida):
    emergencia_id, lote_pm = vencida
    r = client.get(f"/api/bonita/emergencias/{emergencia_id}/ofertas", headers=CLAVE)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["emergencia_id"] == emergencia_id
    assert cuerpo["ronda"] == 1
    assert cuerpo["gravedad"] == "ALTO"
    assert [(l["tipo_recurso"], l["cantidad"], l["tipo"]) for l in cuerpo["lotes"]] == [
        ("PARAMEDICO", 10, "PRINCIPAL"), (None, 3, "PRINCIPAL")]
    assert cuerpo["ofertas"] == [{
        "cuit": CRUZ_ROJA, "ong": "Cruz Roja Argentina", "version": 2,
        "items": [{"lote_id": lote_pm, "tipo_recurso": "PARAMEDICO", "cantidad": 4}],
    }]


def test_pasa_a_en_evaluacion_y_repetirlo_devuelve_lo_mismo(client, seeded, vencida):
    url = f"/api/bonita/emergencias/{vencida[0]}/ofertas"
    primera = client.get(url, headers=CLAVE)
    assert _estado(seeded, vencida[0]) is EstadoEmergencia.EN_EVALUACION
    segunda = client.get(url, headers=CLAVE)
    assert segunda.status_code == 200 and segunda.json() == primera.json()


def test_una_oferta_retirada_no_figura(client, seeded, vencida):
    with seeded() as s:
        o = s.query(Oferta).one()
        o.version_actual = 3  # versión sin ítems = retirada
        s.commit()
    r = client.get(f"/api/bonita/emergencias/{vencida[0]}/ofertas", headers=CLAVE)
    assert r.json()["ofertas"] == []


def test_con_la_ventana_abierta_es_409_y_no_cambia_el_estado(client, seeded, vencida):
    with seeded() as s:
        s.get(Emergencia, vencida[0]).ventana_ofertas_fin = _sin_zona(timedelta(hours=1))
        s.commit()
    r = client.get(f"/api/bonita/emergencias/{vencida[0]}/ofertas", headers=CLAVE)
    assert r.status_code == 409
    assert _estado(seeded, vencida[0]) is EstadoEmergencia.CONVOCATORIA


def test_ya_adjudicada_es_409(client, seeded, vencida):
    with seeded() as s:
        s.get(Emergencia, vencida[0]).estado = EstadoEmergencia.ADJUDICACION
        s.commit()
    assert client.get(f"/api/bonita/emergencias/{vencida[0]}/ofertas", headers=CLAVE).status_code == 409


def test_emergencia_inexistente_es_404(client):
    assert client.get("/api/bonita/emergencias/9999/ofertas", headers=CLAVE).status_code == 404


def test_en_evaluacion_la_ong_ya_no_puede_ofertar(client, seeded, vencida):
    client.get(f"/api/bonita/emergencias/{vencida[0]}/ofertas", headers=CLAVE)
    r = client.post("/api/auth/login", json={"username": "ong.bomberos", "password": PASSWORD})
    assert r.status_code == 200
    r = client.post(f"/api/emergencias/{vencida[0]}/ofertas",
                    json={"items": [{"lote_id": vencida[1], "recurso": "p", "cantidad": 1}]})
    assert r.status_code == 400 and "cerró" in r.json()["detail"]
