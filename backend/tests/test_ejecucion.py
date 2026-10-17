"""Después de adjudicar: monitoreo, finalización de cada ONG, cierre bilateral, evento CIERRE y avisos.
Bonita va mockeado (`responses`); la secuencia real se prueba con los escenarios contra Bonita."""
from urllib.parse import urlparse

import pytest
import responses
from sqlalchemy import select

from app.models import (
    Emergencia, EstadoEmergencia, EstadoOferta, Gravedad, Lote, Municipio, Notificacion, Oferta, OfertaItem, Ong,
)
from tests.test_ciclo import BASE, CASE, CLAVE, BOMBEROS, CRUZ_ROJA, _estado, _mock_tarea, _tarea_completada

TAREA_MONITOREAR = "Monitorear Ejecucion del Despliegue"
TAREA_FINALIZAR = "Confirmar Finalizacion de Actividades"
TAREA_VALIDAR = "Validar Cierre Operativo Bilateral"


@pytest.fixture
def en_ejecucion(seeded):
    """Emergencia EN_EJECUCION con las dos ONGs adjudicadas (4 y 2 paramédicos)."""
    with seeded() as s:
        e = Emergencia(municipio_id=s.query(Municipio).one().id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO,
                       zona_afectada="Centro", descripcion="d", bonita_case_id=CASE,
                       estado=EstadoEmergencia.EN_EJECUCION)
        e.lotes = [Lote(recurso="Paramédico", tipo_recurso="PARAMEDICO", cantidad=10, unidad="personas")]
        s.add(e)
        s.flush()
        for cuit, cantidad in ((CRUZ_ROJA, 4), (BOMBEROS, 2)):
            o = Oferta(emergencia_id=e.id, ong_id=s.query(Ong).filter_by(cuit=cuit).one().id,
                       estado=EstadoOferta.ADJUDICADA)
            o.items = [OfertaItem(version=1, lote_id=e.lotes[0].id, recurso="Paramédico", cantidad=cantidad)]
            s.add(o)
        s.commit()
        return e.id


def _cambiar(seeded, emergencia_id, **cambios):
    with seeded() as s:
        e = s.get(Emergencia, emergencia_id)
        for k, v in cambios.items():
            setattr(e, k, v)
        s.commit()


def _estado_oferta(seeded, emergencia_id, cuit):
    with seeded() as s:
        return s.scalar(select(Oferta).join(Ong).where(Oferta.emergencia_id == emergencia_id, Ong.cuit == cuit)).estado


def _logins(username):
    return [c for c in responses.calls
            if urlparse(c.request.url).path.endswith("/loginservice") and f"username={username}&" in c.request.body]


def _monitoreando(seeded, emergencia_id):
    _cambiar(seeded, emergencia_id, monitoreo_iniciado_en=_ahora())


def _ahora():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


# --- lo que ve cada perfil ---

def test_el_detalle_muestra_la_ejecucion_y_la_ong_solo_ve_la_suya(login, en_ejecucion):
    ver = lambda usuario: login(usuario).get(f"/api/emergencias/{en_ejecucion}").json()["ejecucion"]

    coordinador = ver("coordinador.regional")
    assert (coordinador["monitoreo_iniciado"], coordinador["cierre_validado"], coordinador["todas_finalizadas"]) == (
        False, False, False)
    assert {(o["cuit"], o["estado"]) for o in coordinador["ongs"]} == {(CRUZ_ROJA, "ADJUDICADA"), (BOMBEROS, "ADJUDICADA")}
    assert len(ver("operador.municipal")["ongs"]) == 2
    assert [o["cuit"] for o in ver("ong.bomberos")["ongs"]] == [BOMBEROS]


def test_antes_de_adjudicar_no_hay_ejecucion(login, seeded, en_ejecucion):
    _cambiar(seeded, en_ejecucion, estado=EstadoEmergencia.ADJUDICACION)
    assert login("coordinador.regional").get(f"/api/emergencias/{en_ejecucion}").json()["ejecucion"] is None


# --- monitoreo del Coordinador ---

@responses.activate
def test_el_coordinador_monitorea_y_se_completa_la_tarea_de_bonita(login, seeded, en_ejecucion):
    _mock_tarea(TAREA_MONITOREAR)

    r = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/monitorear")

    assert r.status_code == 200 and r.json()["ejecucion"]["monitoreo_iniciado"] is True
    assert _tarea_completada() and len(_logins("coordinador.regional")) == 1
    r = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/monitorear")
    assert r.status_code == 409 and "ya empezó" in r.json()["detail"]


@responses.activate
def test_si_bonita_no_tiene_la_tarea_de_monitoreo_no_cambia_nada(login, seeded, en_ejecucion):
    _mock_tarea("Otra tarea")

    r = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/monitorear")

    assert r.status_code == 409
    with seeded() as s:
        assert s.get(Emergencia, en_ejecucion).monitoreo_iniciado_en is None


def test_el_monitoreo_es_del_coordinador_y_de_una_emergencia_en_ejecucion(login, seeded, en_ejecucion):
    for usuario in ("operador.municipal", "ong.cruzroja", "auditor"):
        assert login(usuario).post(f"/api/emergencias/{en_ejecucion}/monitorear").status_code == 403, usuario
    _cambiar(seeded, en_ejecucion, estado=EstadoEmergencia.ADJUDICACION)
    assert login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/monitorear").status_code == 409


# --- finalizar actividad ---

@responses.activate
def test_cada_ong_finaliza_y_al_terminar_todas_se_completa_la_tarea_de_bonita(login, seeded, en_ejecucion):
    _monitoreando(seeded, en_ejecucion)
    _mock_tarea(TAREA_FINALIZAR)

    primera = login("ong.cruzroja").post(f"/api/emergencias/{en_ejecucion}/finalizar")

    assert primera.status_code == 200 and primera.json()["ejecucion"]["todas_finalizadas"] is False
    assert _estado_oferta(seeded, en_ejecucion, CRUZ_ROJA) is EstadoOferta.FINALIZADA
    assert not _tarea_completada()  # todavía falta Bomberos
    logins_antes = len(_logins("ong.cruzroja"))
    logins_antes_bomberos = len(_logins("ong.bomberos"))

    ultima = login("ong.bomberos").post(f"/api/emergencias/{en_ejecucion}/finalizar")

    assert ultima.status_code == 200 and ultima.json()["ejecucion"]["todas_finalizadas"] is True
    assert _estado_oferta(seeded, en_ejecucion, BOMBEROS) is EstadoOferta.FINALIZADA
    assert _tarea_completada()
    # la tarea la completa con su propio usuario la ONG que terminó última
    assert len(_logins("ong.bomberos")) > logins_antes_bomberos
    assert len(_logins("ong.cruzroja")) == logins_antes


@responses.activate
def test_finalizar_dos_veces_no_cambia_nada(login, seeded, en_ejecucion):
    _monitoreando(seeded, en_ejecucion)

    c = login("ong.bomberos")
    assert c.post(f"/api/emergencias/{en_ejecucion}/finalizar").status_code == 200
    assert c.post(f"/api/emergencias/{en_ejecucion}/finalizar").status_code == 200
    assert _estado_oferta(seeded, en_ejecucion, BOMBEROS) is EstadoOferta.FINALIZADA


def test_no_se_finaliza_sin_monitoreo_ni_sin_estar_adjudicada(login, seeded, en_ejecucion):
    r = login("ong.cruzroja").post(f"/api/emergencias/{en_ejecucion}/finalizar")
    assert r.status_code == 409 and "monitoreo" in r.json()["detail"]

    _monitoreando(seeded, en_ejecucion)
    with seeded() as s:
        s.scalar(select(Oferta).join(Ong).where(Ong.cuit == BOMBEROS)).estado = EstadoOferta.NO_ADJUDICADA
        s.commit()
    r = login("ong.bomberos").post(f"/api/emergencias/{en_ejecucion}/finalizar")
    assert r.status_code == 403 and "no fue adjudicada" in r.json()["detail"]
    for usuario in ("coordinador.regional", "operador.municipal", "auditor"):
        assert login(usuario).post(f"/api/emergencias/{en_ejecucion}/finalizar").status_code == 403, usuario


@responses.activate
def test_si_bonita_falla_al_finalizar_la_ultima_la_oferta_no_queda_marcada(login, seeded, en_ejecucion):
    _monitoreando(seeded, en_ejecucion)
    login("ong.bomberos").post(f"/api/emergencias/{en_ejecucion}/finalizar")
    _mock_tarea("Otra tarea")

    r = login("ong.cruzroja").post(f"/api/emergencias/{en_ejecucion}/finalizar")

    assert r.status_code == 409
    assert _estado_oferta(seeded, en_ejecucion, CRUZ_ROJA) is EstadoOferta.ADJUDICADA


# --- validar el cierre ---

def _finalizadas(seeded, emergencia_id):
    with seeded() as s:
        for o in s.scalars(select(Oferta).where(Oferta.emergencia_id == emergencia_id)):
            o.estado = EstadoOferta.FINALIZADA
        s.commit()


@responses.activate
def test_el_coordinador_valida_el_cierre_cuando_todas_finalizaron(login, seeded, en_ejecucion):
    _monitoreando(seeded, en_ejecucion)
    _finalizadas(seeded, en_ejecucion)
    _mock_tarea(TAREA_VALIDAR)

    r = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/validar-cierre")

    assert r.status_code == 200 and r.json()["ejecucion"]["cierre_validado"] is True
    assert _tarea_completada() and len(_logins("coordinador.regional")) == 1
    # Bonita libera y avisa: hasta ese evento la emergencia sigue en ejecución
    assert _estado(seeded, en_ejecucion) is EstadoEmergencia.EN_EJECUCION
    again = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/validar-cierre")
    assert again.status_code == 409 and "ya fue validado" in again.json()["detail"]


def test_no_se_valida_el_cierre_si_falta_alguna_ong(login, seeded, en_ejecucion):
    _monitoreando(seeded, en_ejecucion)
    with seeded() as s:
        s.scalar(select(Oferta).join(Ong).where(Ong.cuit == CRUZ_ROJA)).estado = EstadoOferta.FINALIZADA
        s.commit()

    r = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/validar-cierre")

    assert r.status_code == 409 and "Bomberos Voluntarios" in r.json()["detail"] and "Cruz Roja" not in r.json()["detail"]
    for usuario in ("operador.municipal", "ong.cruzroja", "auditor"):
        assert login(usuario).post(f"/api/emergencias/{en_ejecucion}/validar-cierre").status_code == 403, usuario


# --- evento CIERRE de Bonita ---

def _evento_cierre(client, emergencia_id, cuits, clave=CLAVE):
    return client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=clave,
                       json={"tipo": "CIERRE", "cuits": cuits})


def test_el_evento_de_cierre_resuelve_la_emergencia_y_avisa_a_las_ongs_cerradas(client, seeded, en_ejecucion):
    assert _evento_cierre(client, en_ejecucion, [CRUZ_ROJA]).status_code == 204

    assert _estado(seeded, en_ejecucion) is EstadoEmergencia.RESUELTA
    with seeded() as s:
        avisos = s.scalars(select(Notificacion)).all()
        assert [a.ong_id for a in avisos] == [s.query(Ong).filter_by(cuit=CRUZ_ROJA).one().id]
        assert f"#{en_ejecucion} se cerró" in avisos[0].texto


def test_repetir_el_evento_de_cierre_no_duplica_los_avisos(client, seeded, en_ejecucion):
    _evento_cierre(client, en_ejecucion, [CRUZ_ROJA, BOMBEROS])

    assert _evento_cierre(client, en_ejecucion, [CRUZ_ROJA, BOMBEROS]).status_code == 204

    with seeded() as s:
        assert s.query(Notificacion).count() == 2


def test_el_evento_de_cierre_exige_la_clave_el_estado_y_datos(client, seeded, en_ejecucion):
    assert _evento_cierre(client, en_ejecucion, [CRUZ_ROJA], clave={}).status_code == 401
    assert _evento_cierre(client, en_ejecucion, []).status_code == 422
    assert _evento_cierre(client, 9999, [CRUZ_ROJA]).status_code == 404
    _cambiar(seeded, en_ejecucion, estado=EstadoEmergencia.ADJUDICACION)
    assert _evento_cierre(client, en_ejecucion, [CRUZ_ROJA]).status_code == 409


# --- avisos de la ONG ---

def test_la_ong_ve_solo_sus_avisos_y_los_marca_leidos(client, login, seeded, en_ejecucion):
    _evento_cierre(client, en_ejecucion, [CRUZ_ROJA, BOMBEROS])

    avisos = login("ong.cruzroja").get("/api/notificaciones").json()
    assert len(avisos) == 1 and avisos[0]["leida"] is False and avisos[0]["emergencia_id"] == en_ejecucion
    assert len(login("ong.bomberos").get("/api/notificaciones").json()) == 1

    r = login("ong.cruzroja").post(f"/api/notificaciones/{avisos[0]['id']}/leida")
    assert r.status_code == 200 and r.json()["leida"] is True
    assert login("ong.cruzroja").get("/api/notificaciones").json()[0]["leida"] is True
    assert login("ong.bomberos").get("/api/notificaciones").json()[0]["leida"] is False


def test_nadie_marca_el_aviso_de_otra_ong_y_los_demas_perfiles_no_tienen_avisos(client, login, en_ejecucion):
    _evento_cierre(client, en_ejecucion, [CRUZ_ROJA])
    aviso = login("ong.cruzroja").get("/api/notificaciones").json()[0]["id"]

    assert login("ong.bomberos").post(f"/api/notificaciones/{aviso}/leida").status_code == 404
    assert login("ong.cruzroja").post("/api/notificaciones/9999/leida").status_code == 404
    for usuario in ("coordinador.regional", "operador.municipal", "auditor"):
        assert login(usuario).get("/api/notificaciones").json() == [], usuario
        assert login(usuario).post(f"/api/notificaciones/{aviso}/leida").status_code == 403, usuario
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/notificaciones").status_code == 401


def test_los_avisos_llegan_del_mas_nuevo_al_mas_viejo(client, login, seeded, en_ejecucion):
    with seeded() as s:
        ong = s.query(Ong).filter_by(cuit=CRUZ_ROJA).one().id
        for texto in ("primero", "segundo"):
            s.add(Notificacion(ong_id=ong, emergencia_id=en_ejecucion, texto=texto))
        s.commit()

    assert [a["texto"] for a in login("ong.cruzroja").get("/api/notificaciones").json()] == ["segundo", "primero"]
