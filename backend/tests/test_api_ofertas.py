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




def test_miembros_ven_ofertas_del_consorcio(api_login, seeded, abierta):
    eid, lotes = abierta
    with seeded() as s:
        from app.models import Ong
        bomberos = s.query(Ong).filter_by(nombre="Bomberos Voluntarios").one().id
    c = api_login("ong.cruzroja")
    cid = c.post(f"/api/emergencias/{eid}/consorcios", json={"nombre": "Alianza Norte"}).json()["id"]
    c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 60, 20))
    c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": bomberos})

    c = api_login("ong.bomberos")
    # Invitada sin aceptar: todavía no ve nada ajeno.
    assert c.get(f"/api/emergencias/{eid}/ofertas").json() == []
    c.post(f"/api/consorcios/{cid}/respuesta", json={"acepta": True})
    ofertas = c.get(f"/api/emergencias/{eid}/ofertas").json()
    assert [(o["ong_nombre"], o["consorcio_nombre"], o["consorcio_id"]) for o in ofertas] == [
        ("Cruz Roja Argentina", "Alianza Norte", cid)]


def test_ong_ajena_no_ve_ofertas_del_consorcio(api_login, seeded, abierta):
    eid, lotes = abierta
    with seeded() as s:
        from app.models import Ong, Rol, Usuario
        from app.core.security import hash_password
        ajena = Ong(nombre="Cáritas", cuit="30-11111111-1")
        s.add(ajena)
        s.flush()
        s.add(Usuario(username="ong.caritas", password_hash=hash_password(PASSWORD), nombre="Cáritas",
                      rol=Rol.ONG, ong_id=ajena.id))
        bomberos = s.query(Ong).filter_by(nombre="Bomberos Voluntarios").one().id
        s.commit()
    c = api_login("ong.cruzroja")
    cid = c.post(f"/api/emergencias/{eid}/consorcios", json={"nombre": "Alianza Norte"}).json()["id"]
    c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 60, 20))
    c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": bomberos})
    api_login("ong.bomberos").post(f"/api/consorcios/{cid}/respuesta", json={"acepta": True})

    assert api_login("ong.caritas").get(f"/api/emergencias/{eid}/ofertas").json() == []


def test_consorcio_de_un_solo_miembro_no_abre_ofertas(api_login, seeded, abierta):
    """Sin 2 miembros aceptados el consorcio no es válido: nadie ve ofertas ajenas."""
    eid, lotes = abierta
    c = api_login("ong.bomberos")
    c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 10, 5))
    api_login("ong.cruzroja").post(f"/api/emergencias/{eid}/consorcios", json={"nombre": "Sola"})
    assert [o["ong_nombre"] for o in api_login("ong.cruzroja").get(f"/api/emergencias/{eid}/ofertas").json()] == []


def test_ofertas_traen_consorcio_para_el_municipio(api_login, seeded, abierta):
    eid, lotes = abierta
    with seeded() as s:
        from app.models import Ong
        bomberos = s.query(Ong).filter_by(nombre="Bomberos Voluntarios").one().id
    c = api_login("ong.cruzroja")
    cid = c.post(f"/api/emergencias/{eid}/consorcios", json={"nombre": "Alianza Norte"}).json()["id"]
    c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 60, 20))
    c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": bomberos})
    c = api_login("ong.bomberos")
    c.post(f"/api/consorcios/{cid}/respuesta", json={"acepta": True})
    c.post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 10, 5))

    ofertas = api_login("operador.municipal").get(f"/api/emergencias/{eid}/ofertas").json()
    assert {o["ong_nombre"]: o["consorcio_nombre"] for o in ofertas} == {
        "Cruz Roja Argentina": "Alianza Norte", "Bomberos Voluntarios": "Alianza Norte"}


def test_oferta_sin_consorcio_trae_campos_nulos(api_login, abierta):
    eid, lotes = abierta
    o = api_login("ong.cruzroja").post(f"/api/emergencias/{eid}/ofertas", json=_items(lotes, 60, 20)).json()
    assert o["consorcio_id"] is None and o["consorcio_nombre"] is None
