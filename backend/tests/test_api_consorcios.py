"""Consorcios por la API JSON de la SPA: formación, listado y selector de ONGs."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Emergencia, EstadoEmergencia, Gravedad, Municipio, Ong


@pytest.fixture
def emergencia_id(seeded):
    with seeded() as s:
        e = Emergencia(municipio_id=s.query(Municipio).one().id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO,
                       zona_afectada="Centro", descripcion="Río desbordado", bonita_case_id=4242,
                       estado=EstadoEmergencia.CONVOCATORIA,
                       ventana_ofertas_fin=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2))
        s.add(e)
        s.commit()
        return e.id


def _ong_id(seeded, nombre):
    with seeded() as s:
        return s.query(Ong).filter_by(nombre=nombre).one().id


def _crear(c, eid, nombre="Alianza Norte"):
    return c.post(f"/api/emergencias/{eid}/consorcios", json={"nombre": nombre})


def test_flujo_crear_invitar_aceptar(login, seeded, emergencia_id):
    c = login("ong.cruzroja")
    r = _crear(c, emergencia_id)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["valido"] is False and r.json()["ong_lider_nombre"] == "Cruz Roja Argentina"

    bomberos = _ong_id(seeded, "Bomberos Voluntarios")
    r = c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": bomberos})
    assert r.status_code == 201, r.text
    assert {m["estado"] for m in r.json()["miembros"]} == {"ACEPTADA", "INVITADA"}

    c = login("ong.bomberos")
    r = c.post(f"/api/consorcios/{cid}/respuesta", json={"acepta": True})
    assert r.status_code == 200, r.text

    lista = c.get(f"/api/emergencias/{emergencia_id}/consorcios").json()
    assert len(lista) == 1 and lista[0]["valido"] is True and lista[0]["disuelto"] is False
    assert {m["ong_nombre"] for m in lista[0]["miembros"]} == {"Cruz Roja Argentina", "Bomberos Voluntarios"}


def test_salida_y_disolucion(login, seeded, emergencia_id):
    c = login("ong.cruzroja")
    cid = _crear(c, emergencia_id).json()["id"]
    c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": _ong_id(seeded, "Bomberos Voluntarios")})
    login("ong.bomberos").post(f"/api/consorcios/{cid}/respuesta", json={"acepta": True})
    assert login("ong.bomberos").post(f"/api/consorcios/{cid}/salida").status_code == 204
    c = login("ong.cruzroja")
    assert c.delete(f"/api/consorcios/{cid}").status_code == 204
    assert c.get(f"/api/emergencias/{emergencia_id}/consorcios").json() == []


def test_municipio_no_puede_crear(login, emergencia_id):
    assert _crear(login("operador.municipal"), emergencia_id).status_code == 403


def test_roles_que_no_son_ong_no_operan_consorcios(login, emergencia_id):
    cid = _crear(login("ong.cruzroja"), emergencia_id).json()["id"]
    for usuario in ("operador.municipal", "coordinador.regional", "auditor"):
        c = login(usuario)
        assert c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": 1}).status_code == 403
        assert c.post(f"/api/consorcios/{cid}/respuesta", json={"acepta": True}).status_code == 403
        assert c.post(f"/api/consorcios/{cid}/salida").status_code == 403
        assert c.delete(f"/api/consorcios/{cid}").status_code == 403
        assert c.get("/api/ongs").status_code == 403


def test_sin_sesion_da_401(client, emergencia_id):
    assert client.get(f"/api/emergencias/{emergencia_id}/consorcios").status_code == 401


def test_municipio_y_auditor_ven_el_listado(login, emergencia_id):
    _crear(login("ong.cruzroja"), emergencia_id)
    for usuario in ("operador.municipal", "coordinador.regional", "auditor"):
        r = login(usuario).get(f"/api/emergencias/{emergencia_id}/consorcios")
        assert r.status_code == 200 and len(r.json()) == 1


def test_consorcio_inexistente_da_404(login):
    c = login("ong.cruzroja")
    assert c.post("/api/consorcios/9999/invitaciones", json={"ong_id": 1}).status_code == 404
    assert c.post("/api/consorcios/9999/respuesta", json={"acepta": True}).status_code == 404
    assert c.post("/api/consorcios/9999/salida").status_code == 404
    assert c.delete("/api/consorcios/9999").status_code == 404
    assert c.get("/api/emergencias/9999/consorcios").status_code == 404
    assert _crear(c, 9999).status_code == 404


def test_ong_inexistente_al_invitar_da_404(login, emergencia_id):
    c = login("ong.cruzroja")
    cid = _crear(c, emergencia_id).json()["id"]
    assert c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": 9999}).status_code == 404


@pytest.mark.parametrize("nombre", ["", " ", "a", "x" * 81])
def test_nombre_invalido_da_422(login, emergencia_id, nombre):
    assert _crear(login("ong.cruzroja"), emergencia_id, nombre).status_code == 422


def test_cuerpo_mal_formado_da_422(login, emergencia_id):
    c = login("ong.cruzroja")
    cid = _crear(c, emergencia_id).json()["id"]
    assert c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": "x"}).status_code == 422
    assert c.post(f"/api/consorcios/{cid}/respuesta", json={}).status_code == 422


def test_nombre_repetido_da_409(login, emergencia_id):
    _crear(login("ong.cruzroja"), emergencia_id)
    r = _crear(login("ong.bomberos"), emergencia_id)
    assert r.status_code == 409 and "ese nombre" in r.json()["detail"]


def test_choque_de_nombre_concurrente_da_409(login, emergencia_id, monkeypatch):
    """Si dos pedidos pasan la verificación a la vez, la restricción única de la tabla da 409 y no 500."""
    from sqlalchemy.exc import IntegrityError
    from app.services import consorcios

    def explota(db, *, emergencia, ong, nombre):
        raise IntegrityError("insert", {}, Exception("unique"))

    monkeypatch.setattr(consorcios, "crear", explota)
    r = _crear(login("ong.bomberos"), emergencia_id)
    assert r.status_code == 409 and "ese nombre" in r.json()["detail"]


def test_ventana_cerrada_da_409_pero_el_listado_responde(login, seeded, emergencia_id):
    c = login("ong.cruzroja")
    _crear(c, emergencia_id)
    with seeded() as s:
        s.get(Emergencia, emergencia_id).ventana_ofertas_fin = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        s.commit()
    assert _crear(c, emergencia_id, "Otra").status_code == 409
    assert c.get(f"/api/emergencias/{emergencia_id}/consorcios").status_code == 200


def test_listado_de_ongs_excluye_propia_y_ocupadas(login, seeded, emergencia_id):
    with seeded() as s:
        s.add_all([Ong(nombre="Cáritas", cuit="30-11111111-1"), Ong(nombre="Sin CUIT", cuit=None)])
        s.commit()
    c = login("ong.cruzroja")
    nombres = lambda r: sorted(o["nombre"] for o in r.json())  # noqa: E731
    r = c.get("/api/ongs")
    assert nombres(r) == ["Bomberos Voluntarios", "Cáritas"]
    assert set(r.json()[0]) == {"id", "nombre", "cuit"}

    cid = _crear(c, emergencia_id).json()["id"]
    c.post(f"/api/consorcios/{cid}/invitaciones", json={"ong_id": _ong_id(seeded, "Bomberos Voluntarios")})
    assert nombres(c.get(f"/api/ongs?emergencia_id={emergencia_id}")) == ["Cáritas"]
    assert nombres(c.get("/api/ongs")) == ["Bomberos Voluntarios", "Cáritas"]
    assert c.get("/api/ongs?emergencia_id=9999").status_code == 404


@pytest.mark.parametrize("nombre", ["Alianza\x00Norte", "Alianza\nNorte"])
def test_nombre_con_caracteres_de_control_422(login, emergencia_id, nombre):
    assert _crear(login("ong.cruzroja"), emergencia_id, nombre).status_code == 422


@pytest.mark.parametrize("ruta", [
    "/api/consorcios/2147483648/respuesta", "/api/consorcios/0/salida", "/api/emergencias/2147483648/consorcios",
])
def test_ids_fuera_de_int32_dan_422(login, ruta):
    assert login("ong.cruzroja").post(ruta, json={"acepta": True, "nombre": "Alianza"}).status_code == 422


def test_ongs_con_emergencia_fuera_de_int32_422(login):
    assert login("ong.cruzroja").get("/api/ongs?emergencia_id=2147483648").status_code == 422
