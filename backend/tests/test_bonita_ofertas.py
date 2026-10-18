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
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    r = client.post(f"/api/emergencias/{vencida[0]}/ofertas",
                    json={"items": [{"lote_id": vencida[1], "recurso": "p", "cantidad": 1}]})
    assert r.status_code == 400 and "cerró" in r.json()["detail"]


# --- POST /api/bonita/emergencias/{id}/eventos (EVALUACION) ---

def _evaluacion(emergencia_id, lote_id, ronda=1):
    """Lo que la API Nacional devuelve en POST /evaluaciones (contratos.md, 3.1)."""
    return {
        "emergencia_id": emergencia_id, "ronda": ronda, "cobertura_completa": False, "porcentaje_cobertura": 40.0,
        "lotes": [{"lote_id": lote_id, "tipo_recurso": "PARAMEDICO", "pedido": 10, "reservado": 4,
                   "porcentaje": 40.0, "cubierto": False}],
        "ongs": [{"cuit": CRUZ_ROJA, "ong": "Cruz Roja Argentina", "referencia": f"emg-{emergencia_id}-r1-{CRUZ_ROJA}",
                  "estado": "RESERVADA",
                  "items": [{"lote_id": lote_id, "tipo_recurso": "PARAMEDICO", "ofrecido": 4, "reservado": 4,
                             "nivel": "PARCIAL", "riesgo_permitido": "MEDIO", "asignacion_sugerida": "APOYO",
                             "observaciones": ["SALUD_PREHOSP vigente hasta riesgo MEDIO; la emergencia es ALTO"]}]}],
    }


@pytest.fixture
def en_evaluacion(client, vencida):
    client.get(f"/api/bonita/emergencias/{vencida[0]}/ofertas", headers=CLAVE)  # Bonita pide el consolidado
    return vencida


def _evento(client, emergencia_id, resultado, clave=CLAVE):
    return client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=clave,
                       json={"tipo": "EVALUACION", "resultado": resultado})


def _ver(client, username, emergencia_id):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client.get(f"/api/emergencias/{emergencia_id}").json()


def test_el_evento_sin_clave_es_401(client, en_evaluacion):
    emergencia_id, lote = en_evaluacion
    assert _evento(client, emergencia_id, _evaluacion(emergencia_id, lote), clave={}).status_code == 401


def test_el_evento_guarda_la_evaluacion_y_el_coordinador_la_ve(client, en_evaluacion):
    emergencia_id, lote = en_evaluacion
    resultado = _evaluacion(emergencia_id, lote)

    assert _evento(client, emergencia_id, resultado).status_code == 204

    assert _ver(client, "coordinador.regional", emergencia_id)["evaluacion"] == resultado
    assert _ver(client, "operador.municipal", emergencia_id)["evaluacion"] == resultado
    assert _ver(client, "auditor", emergencia_id)["evaluacion"] == resultado


def test_la_ong_no_ve_la_evaluacion_y_antes_del_evento_no_hay(client, en_evaluacion):
    emergencia_id, lote = en_evaluacion
    assert _ver(client, "coordinador.regional", emergencia_id)["evaluacion"] is None
    _evento(client, emergencia_id, _evaluacion(emergencia_id, lote))
    assert _ver(client, "ong.cruzroja", emergencia_id)["evaluacion"] is None


def test_repetir_el_evento_deja_el_mismo_resultado(client, en_evaluacion):
    emergencia_id, lote = en_evaluacion
    resultado = _evaluacion(emergencia_id, lote)
    assert _evento(client, emergencia_id, resultado).status_code == 204
    assert _evento(client, emergencia_id, resultado).status_code == 204
    assert _ver(client, "coordinador.regional", emergencia_id)["evaluacion"] == resultado


def test_el_evento_es_409_si_la_emergencia_no_espera_evaluacion(client, vencida):
    emergencia_id, lote = vencida  # sigue CONVOCATORIA: Bonita todavía no pidió el consolidado
    assert _evento(client, emergencia_id, _evaluacion(emergencia_id, lote)).status_code == 409


def test_el_evento_de_otra_emergencia_o_ronda_es_409(client, en_evaluacion):
    emergencia_id, lote = en_evaluacion
    assert _evento(client, emergencia_id, _evaluacion(emergencia_id + 1, lote)).status_code == 409
    assert _evento(client, emergencia_id, _evaluacion(emergencia_id, lote, ronda=2)).status_code == 409


def test_el_evento_de_una_emergencia_inexistente_es_404_y_uno_mal_formado_es_422(client, en_evaluacion):
    emergencia_id, lote = en_evaluacion
    assert _evento(client, 9999, _evaluacion(9999, lote)).status_code == 404
    r = client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=CLAVE,
                    json={"tipo": "OTRO", "resultado": {}})
    assert r.status_code == 422
