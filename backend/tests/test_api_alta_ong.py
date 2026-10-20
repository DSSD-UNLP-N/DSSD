import responses

from app.core.config import get_settings
from tests.test_alta_ong import _mock_bonita_ok

URL = "/api/ongs/alta"


def _body(**kw):
    base = dict(ong_nombre="Techo Digno", cuit="30-71234567-8", nombre="Ana Paz", username="ong.techo",
                password="secreto123",
                rubros=[{"tipo_recurso": "PARAMEDICO", "cantidad_total": 4},
                        {"tipo_recurso": "RACION_ALIMENTO", "cantidad_total": 0}])
    base.update(kw)
    return base


@responses.activate
def test_alta_sin_sesion_201(client, seeded, nacional):
    _mock_bonita_ok()
    r = client.post(URL, json=_body())
    assert r.status_code == 201
    assert r.json()["cuit"] == "30-71234567-8"
    login = client.post("/api/auth/login", json={"username": "ong.techo", "password": "secreto123"})
    assert login.status_code == 200
    assert login.json()["rol"] == "ONG"


@responses.activate
def test_alta_recorta_espacios(client, seeded, nacional):
    _mock_bonita_ok()
    r = client.post(URL, json=_body(username="  ong.caritas "))
    assert r.status_code == 201
    assert nacional.ongs_registradas[0]["username"] == "ong.caritas"


def test_alta_rubros_repetidos_422(client, seeded, nacional):
    rubros = [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}] * 2
    assert client.post(URL, json=_body(rubros=rubros)).status_code == 422


def test_alta_sin_rubros_422(client, seeded, nacional):
    assert client.post(URL, json=_body(rubros=[])).status_code == 422


def test_alta_cantidad_negativa_422(client, seeded, nacional):
    rubros = [{"tipo_recurso": "PARAMEDICO", "cantidad_total": -1}]
    assert client.post(URL, json=_body(rubros=rubros)).status_code == 422


def test_alta_duplicado_409_detail_en_espanol(client, seeded, nacional):
    r = client.post(URL, json=_body(username="ong.cruzroja"))
    assert r.status_code == 409
    assert "ya está registrado" in r.json()["detail"]


def test_tipos_recurso_publico(client, seeded, nacional):
    r = client.get(f"{URL}/tipos-recurso")
    assert r.status_code == 200
    assert "PARAMEDICO" in [t["codigo"] for t in r.json()]
    nacional.caido = True
    assert client.get(f"{URL}/tipos-recurso").status_code == 503
