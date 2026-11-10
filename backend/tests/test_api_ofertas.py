"""T-11/T-12 por la API JSON de la SPA: ofertas de las ONGs, versionadas."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Emergencia, EstadoEmergencia, Gravedad, Lote, Municipio
from tests.conftest import PASSWORD


def _emergencia(seeded, *, ventana_fin):
    with seeded() as s:
        municipio = s.query(Municipio).one()
        e = Emergencia(municipio_id=municipio.id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO,
                       zona_afectada="Centro", descripcion="Río desbordado", bonita_case_id=4242,
                       estado=EstadoEmergencia.CONVOCATORIA, ventana_ofertas_fin=ventana_fin)
        e.lotes = [Lote(recurso="Agua", cantidad=100, unidad="litros"),
                   Lote(recurso="Frazadas", cantidad=50, unidad="unidades")]
        s.add(e)
        s.commit()
        return e.id, [l.id for l in e.lotes]


@pytest.fixture
def abierta(seeded):
    # Como la guarda publicar_convocatoria: UTC sin zona (SQLite la descarta).
    return _emergencia(seeded, ventana_fin=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2))


@pytest.fixture
def api_login(client):
    def _login(username):
        client.post("/api/auth/logout")
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return client

    return _login


def _items(lotes, *cantidades):
    return {"items": [{"lote_id": l, "recurso": "x", "cantidad": c} for l, c in zip(lotes, cantidades)]}


def test_una_oferta_cubre_varios_lotes_y_cada_envio_es_una_version(api_login, abierta):
    eid, lotes = abierta
    c = api_login("ong.cruzroja")

    v1 = c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 60, 20)).json()
    assert v1["version_actual"] == 1 and len(v1["items"]) == 2
    assert v1["ong_nombre"] == "Cruz Roja Argentina"

    v2 = c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes[:1], 80)).json()
    assert v2["version_actual"] == 2
    assert [(i["lote_id"], i["cantidad"]) for i in v2["items"]] == [(lotes[0], 80)]


def test_ventana_vencida_rechaza_ofertas(api_login, seeded):
    eid, lotes = _emergencia(seeded, ventana_fin=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1))
    r = api_login("ong.cruzroja").post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 5))
    assert r.status_code == 400 and "cerró" in r.json()["detail"]


def test_lotes_repetidos_o_ajenos_se_rechazan(api_login, abierta):
    eid, lotes = abierta
    c = api_login("ong.cruzroja")
    assert c.post(f"/api/emergencias/{eid}/ofertas", json=_items([lotes[0], lotes[0]], 1, 2)).status_code == 400
    assert c.post(f"/api/emergencias/{eid}/ofertas", json=_items([9999], 1)).status_code == 400


def test_cada_ong_ve_solo_su_oferta_y_el_coordinador_todas(api_login, abierta):
    eid, lotes = abierta
    api_login("ong.cruzroja").post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 1, 1))
    api_login("ong.bomberos").post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 2, 2))

    propias = api_login("ong.bomberos").get(f"/api/emergencias/{eid}/ofertas").json()
    assert [o["ong_nombre"] for o in propias] == ["Bomberos Voluntarios"]
    todas = api_login("coordinador.regional").get(f"/api/emergencias/{eid}/ofertas").json()
    assert len(todas) == 2


def test_fechas_salen_con_zona_utc(api_login, abierta):
    eid, _ = abierta
    e = api_login("coordinador.regional").get(f"/api/emergencias/{eid}").json()
    assert e["ventana_ofertas_fin"].endswith("Z") or e["ventana_ofertas_fin"].endswith("+00:00")
    assert datetime.fromisoformat(e["creada_en"]).tzinfo is not None
