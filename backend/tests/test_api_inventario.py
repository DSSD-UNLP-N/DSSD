"""GET/PUT /api/ong/inventario: la ONG ve y actualiza su inventario; la app lo reenvía al Sistema Nacional."""
import pytest

from app.integrations.nacional import NacionalError
from app.models import Ong
from tests.conftest import BOMBEROS, CRUZ_ROJA

URL = "/api/ong/inventario"


def _por_tipo(ficha):
    return {i["tipo_recurso"]: i for i in ficha["inventario"]}


def test_la_ong_ve_su_inventario_y_sus_certificaciones(login, nacional):
    nacional.comprometido[(CRUZ_ROJA, "PARAMEDICO")] = 1
    r = login("ong.cruzroja").get(URL)
    assert r.status_code == 200
    ficha = r.json()
    assert ficha["cuit"] == CRUZ_ROJA
    assert _por_tipo(ficha)["PARAMEDICO"] == {
        "tipo_recurso": "PARAMEDICO", "nombre": "Paramédico", "unidad": "personas", "cantidad_total": 5,
        "cantidad_comprometida": 1, "disponible": 4, "riesgo_permitido": "CRITICO"}
    assert ficha["certificaciones"][0]["codigo"] == "SALUD_PREHOSP"


def test_cada_ong_ve_solo_el_suyo(login):
    ficha = login("ong.bomberos").get(URL).json()
    assert ficha["cuit"] == BOMBEROS
    assert set(_por_tipo(ficha)) == {"PARAMEDICO"}


def test_actualizar_declara_con_el_cuit_de_la_sesion_y_devuelve_la_ficha(login, nacional):
    rubros = [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 9}, {"tipo_recurso": "AGUA_POTABLE", "cantidad_total": 300}]
    r = login("ong.cruzroja").put(URL, json={"rubros": rubros})
    assert r.status_code == 200
    assert nacional.inventarios == {CRUZ_ROJA: rubros}
    tipos = _por_tipo(r.json())
    assert tipos["PARAMEDICO"]["cantidad_total"] == 9
    assert tipos["AGUA_POTABLE"]["disponible"] == 300
    assert tipos["RACION_ALIMENTO"]["cantidad_total"] == 5000  # lo que no viene no cambia


def test_no_se_puede_declarar_menos_de_lo_comprometido_409(login, nacional):
    nacional.comprometido[(CRUZ_ROJA, "PARAMEDICO")] = 3
    r = login("ong.cruzroja").put(URL, json={"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 2}]})
    assert r.status_code == 409
    assert "3 comprometidos" in r.json()["detail"]


def test_tipo_de_recurso_inexistente_422(login):
    r = login("ong.cruzroja").put(URL, json={"rubros": [{"tipo_recurso": "NAVE_ESPACIAL", "cantidad_total": 1}]})
    assert r.status_code == 422
    assert "NAVE_ESPACIAL" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"rubros": []},
    {"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": -1}]},
    {"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 2**31}]},
    {"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}] * 2},
    {"rubros": [{"tipo_recurso": "", "cantidad_total": 1}]},
    {},
])
def test_entrada_mal_formada_422_sin_llamar_a_nacional(login, nacional, body):
    assert login("ong.cruzroja").put(URL, json=body).status_code == 422
    assert nacional.inventarios == {}


def test_sin_sesion_401(client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]}).status_code == 401


@pytest.mark.parametrize("username", ["operador.municipal", "coordinador.regional", "auditor"])
def test_otros_roles_403(login, username):
    c = login(username)
    assert c.get(URL).status_code == 403
    assert c.put(URL, json={"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]}).status_code == 403


def test_nacional_caido_503(login, nacional):
    c = login("ong.cruzroja")
    nacional.caido = True
    assert c.get(URL).status_code == 503
    assert c.put(URL, json={"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]}).status_code == 503


def test_nacional_falla_al_declarar_503(login, nacional):
    nacional.falla_inventario = NacionalError("Sistema Nacional: PUT falló (500)", 500)
    r = login("ong.cruzroja").put(URL, json={"rubros": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]})
    assert r.status_code == 503


def test_ong_sin_cuit_409(login, seeded):
    with seeded() as s:
        s.query(Ong).filter_by(cuit=CRUZ_ROJA).one().cuit = None
        s.commit()
    assert login("ong.cruzroja").get(URL).status_code == 409


def test_ong_que_nacional_no_conoce_404(login, nacional):
    nacional.inventario = {k: v for k, v in nacional.inventario.items() if k[0] != CRUZ_ROJA}
    r = login("ong.cruzroja").get(URL)
    assert r.status_code == 404
    assert "no está registrada" in r.json()["detail"]
