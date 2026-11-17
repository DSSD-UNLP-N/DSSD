"""Ofertas de las ONGs por la API de la SPA (T-11/T-12): versionadas, y sin pasarse del inventario. Lo que la ONG
ofrece de cada recurso se suma con sus otras ofertas abiertas y se valida contra el inventario del Sistema Nacional
(que va mockeado)."""
from datetime import datetime, timedelta

import pytest

from app.models import Emergencia, EstadoEmergencia, Gravedad, Oferta, OfertaItem, Ong
from tests.conftest import PASSWORD, crear_emergencia, sin_zona


def _con_agua_y_frazadas(seeded, *, ventana_fin):
    return crear_emergencia(seeded, EstadoEmergencia.CONVOCATORIA, descripcion="Río desbordado", bonita_case_id=4242,
                            ventana_ofertas_fin=ventana_fin, ofertas=(),
                            lotes=({"recurso": "Agua", "cantidad": 100, "unidad": "litros"},
                                   {"recurso": "Frazadas", "cantidad": 50, "unidad": "unidades"}))


def _emergencia(seeded, *lotes, horas=2, gravedad=Gravedad.ALTO):
    """Convocatoria abierta con un lote por cada (tipo_recurso, cantidad)."""
    return crear_emergencia(seeded, EstadoEmergencia.CONVOCATORIA, nivel_gravedad=gravedad, bonita_case_id=None,
                            ventana_ofertas_fin=sin_zona(timedelta(hours=horas)), ofertas=(),
                            lotes=[{"recurso": tipo or "Libre", "tipo_recurso": tipo, "cantidad": cantidad, "unidad": "u"}
                                   for tipo, cantidad in lotes])


@pytest.fixture
def abierta(seeded):
    return _con_agua_y_frazadas(seeded, ventana_fin=sin_zona(timedelta(hours=2)))


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


def _ofrecer(c, emergencia, *pares):
    """pares: (lote_id, cantidad)."""
    return c.post(f"/api/emergencias/{emergencia}/ofertas",
                  json={"items": [{"lote_id": l, "recurso": "x", "cantidad": n} for l, n in pares]})


def _ofertas(seeded):
    with seeded() as s:
        return s.query(Oferta).count()


def _items_guardados(seeded, emergencia):
    with seeded() as s:
        oferta = s.query(Oferta).filter_by(emergencia_id=emergencia).one()
        return sorted((i.version, i.lote_id, i.cantidad) for i in s.query(OfertaItem).filter_by(oferta_id=oferta.id))


# --- versiones ---------------------------------------------------------------

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
    eid, lotes = _con_agua_y_frazadas(seeded, ventana_fin=sin_zona(-timedelta(minutes=1)))
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


# --- sin validación en la app ------------------------------------------------
# La app nunca llama a la API Nacional: el inventario y la competencia los valida Bonita al vencer la ventana.

def test_ofertar_no_consulta_a_la_api_nacional_ni_pone_tope(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 20))
    nacional.caido = True  # si la app la llamara, respondería 503
    r = _ofrecer(api_login("ong.cruzroja"), em, (lote, 10))  # tiene 4: lo resuelve la evaluación de Bonita
    assert r.status_code == 201 and r.json()["version_actual"] == 1


# --- retirar ---------------------------------------------------------------
# Retirar un lote = reenviar la oferta sin él (versión nueva); retirarla toda = reenviarla vacía.

def test_retirar_un_lote_deja_una_version_sin_ese_item_y_conserva_el_historial(api_login, seeded):
    em, (a, b) = _emergencia(seeded, ("PARAMEDICO", 5), ("RACION_ALIMENTO", 100))
    c = api_login("ong.cruzroja")
    assert _ofrecer(c, em, (a, 2), (b, 50)).status_code == 201
    r = _ofrecer(c, em, (a, 2))  # retira el lote b
    assert r.status_code == 201
    assert (r.json()["version_actual"], [i["lote_id"] for i in r.json()["items"]], r.json()["retirada"]) == (2, [a], False)
    assert _items_guardados(seeded, em) == [(1, a, 2), (1, b, 50), (2, a, 2)]  # la v1 sigue intacta


def test_retirar_toda_la_oferta(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 5))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 3))
    r = _ofrecer(c, em)
    assert r.status_code == 201
    assert (r.json()["version_actual"], r.json()["items"], r.json()["retirada"]) == (2, [], True)
    assert _items_guardados(seeded, em) == [(1, lote, 3)]  # el historial no se pierde
    # el Coordinador la ve marcada como retirada
    (oferta,) = api_login("coordinador.regional").get(f"/api/emergencias/{em}/ofertas").json()
    assert oferta["retirada"] is True


def test_retirar_no_depende_del_sistema_nacional(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 2))
    nacional.caido = True
    r = _ofrecer(c, em)
    assert r.status_code == 201 and r.json()["retirada"] is True


def test_no_se_puede_retirar_lo_que_no_se_ofreci(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    r = _ofrecer(c, em)
    assert r.status_code == 400 and "No tenés una oferta para retirar" in r.json()["detail"]
    assert _ofertas(seeded) == 0
    _ofrecer(c, em, (lote, 1))
    _ofrecer(c, em)
    assert _ofrecer(c, em).status_code == 400  # ya estaba retirada


def test_con_la_ventana_vencida_no_se_puede_retirar(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 2))
    with seeded() as s:
        s.get(Emergencia, em).ventana_ofertas_fin = sin_zona(-timedelta(minutes=1))
        s.commit()
    r = _ofrecer(c, em)
    assert r.status_code == 400 and "cerró" in r.json()["detail"]


# --- Consorcios: quién ve qué ofertas ---------------------------------------------------------------------------

def test_miembros_ven_ofertas_del_consorcio(api_login, seeded, abierta):
    eid, lotes = abierta
    with seeded() as s:
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
