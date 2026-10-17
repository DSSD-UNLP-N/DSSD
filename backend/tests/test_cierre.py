"""Tests del flujo de cierre bilateral (WP6): evento CIERRE, notificaciones, monitoreo, finalizar y validar cierre."""
import json
from urllib.parse import urlparse

import pytest
import responses
from sqlalchemy import select

from app.core.config import get_settings
from app.models import (
    Emergencia, EstadoEmergencia, EstadoOferta, Gravedad, Lote,
    Municipio, Notificacion, Oferta, OfertaItem, Ong,
)

BASE = get_settings().bonita_base_url
CASE = 7777
CLAVE = {"X-Api-Key": "rescuesync-dev-key"}
CRUZ_ROJA, BOMBEROS = "30-54666544-5", "30-68522415-9"

TAREA_MONITOREAR = "Monitorear Ejecucion del Despliegue"
TAREA_CONFIRMAR = "Confirmar Finalizacion de Actividades"
TAREA_VALIDAR = "Validar Cierre Operativo Bilateral"


@pytest.fixture
def en_ejecucion(seeded):
    """Emergencia EN_EJECUCION con Cruz Roja adjudicada y Bomberos no adjudicada."""
    with seeded() as s:
        e = Emergencia(
            municipio_id=s.query(Municipio).one().id,
            tipo="inundacion",
            nivel_gravedad=Gravedad.ALTO,
            zona_afectada="Centro",
            descripcion="desc",
            bonita_case_id=CASE,
            estado=EstadoEmergencia.EN_EJECUCION,
            monitoreo_completado=False,
        )
        e.lotes = [Lote(recurso="Paramédico", tipo_recurso="PARAMEDICO", cantidad=10, unidad="personas")]
        s.add(e)
        s.flush()
        cruz = s.query(Ong).filter_by(cuit=CRUZ_ROJA).one()
        bomberos = s.query(Ong).filter_by(cuit=BOMBEROS).one()
        o1 = Oferta(emergencia_id=e.id, ong_id=cruz.id, estado=EstadoOferta.ADJUDICADA)
        o1.items = [OfertaItem(version=1, lote_id=e.lotes[0].id, recurso="Paramédico", cantidad=4)]
        o2 = Oferta(emergencia_id=e.id, ong_id=bomberos.id, estado=EstadoOferta.NO_ADJUDICADA)
        o2.items = [OfertaItem(version=1, lote_id=e.lotes[0].id, recurso="Paramédico", cantidad=2)]
        s.add_all([o1, o2])
        s.commit()
        return e.id


# ─── evento CIERRE ─────────────────────────────────────────────────────────────

def test_evento_cierre_pasa_a_resuelta_y_notifica(client, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    r = client.post(
        f"/api/bonita/emergencias/{emergencia_id}/eventos",
        headers=CLAVE,
        json={"tipo": "CIERRE", "cuits": [CRUZ_ROJA]},
    )
    assert r.status_code == 204

    with seeded() as s:
        e = s.get(Emergencia, emergencia_id)
        assert e.estado is EstadoEmergencia.RESUELTA
        avisos = s.scalars(select(Notificacion).where(Notificacion.emergencia_id == emergencia_id)).all()
        assert len(avisos) == 1
        assert "cerrada" in avisos[0].texto.lower()


def test_evento_cierre_idempotente(client, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=CLAVE,
                json={"tipo": "CIERRE", "cuits": [CRUZ_ROJA]})
    # segundo intento no duplica notificaciones
    r = client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=CLAVE,
                    json={"tipo": "CIERRE", "cuits": [CRUZ_ROJA]})
    assert r.status_code == 204
    with seeded() as s:
        assert s.query(Notificacion).filter_by(emergencia_id=emergencia_id).count() == 1


def test_evento_cierre_requiere_en_ejecucion(client, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    # Poner en estado inválido
    with seeded() as s:
        e = s.get(Emergencia, emergencia_id)
        e.estado = EstadoEmergencia.ADJUDICACION
        s.commit()
    r = client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=CLAVE,
                    json={"tipo": "CIERRE", "cuits": [CRUZ_ROJA]})
    assert r.status_code == 409


# ─── notificaciones ────────────────────────────────────────────────────────────

def _crear_notificacion(seeded, emergencia_id, cuit, texto):
    with seeded() as s:
        ong = s.query(Ong).filter_by(cuit=cuit).one()
        s.add(Notificacion(ong_id=ong.id, emergencia_id=emergencia_id, texto=texto))
        s.commit()


def test_ong_ve_sus_notificaciones(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _crear_notificacion(seeded, emergencia_id, CRUZ_ROJA, "Tu oferta fue seleccionada.")
    r = login("ong.cruzroja").get("/api/notificaciones")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert "leida" in data[0]
    assert data[0]["leida"] is False


def test_ong_no_ve_notificaciones_de_otra_ong(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _crear_notificacion(seeded, emergencia_id, BOMBEROS, "Notif de Bomberos")
    r = login("ong.cruzroja").get("/api/notificaciones")
    assert r.status_code == 200
    assert r.json() == []


def test_marcar_notificacion_leida(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _crear_notificacion(seeded, emergencia_id, CRUZ_ROJA, "Mensaje")
    c = login("ong.cruzroja")
    notif_id = c.get("/api/notificaciones").json()[0]["id"]
    r = c.post(f"/api/notificaciones/{notif_id}/leida")
    assert r.status_code == 204
    assert c.get("/api/notificaciones").json()[0]["leida"] is True


def test_ong_no_puede_marcar_notificacion_de_otra(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _crear_notificacion(seeded, emergencia_id, BOMBEROS, "Msg Bomberos")
    # Obtener el id de la notificación de Bomberos mientras estamos logueados como Bomberos
    c = login("ong.bomberos")
    notif_id = c.get("/api/notificaciones").json()[0]["id"]
    # Re-loguearse como Cruz Roja e intentar marcar la notificación de Bomberos
    login("ong.cruzroja")
    r = c.post(f"/api/notificaciones/{notif_id}/leida")
    assert r.status_code == 404


def test_notificaciones_solo_para_ong(login):
    for usuario in ("coordinador.regional", "operador.municipal", "auditor"):
        r = login(usuario).get("/api/notificaciones")
        assert r.status_code == 403, usuario


# ─── monitoreo ─────────────────────────────────────────────────────────────────

def _mock_tarea_bonita(nombre, tarea_id="42"):
    for _ in range(2):
        responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                      headers={"Set-Cookie": f"X-Bonita-API-Token=tok; Path=/"})
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[{"id": tarea_id, "displayName": nombre}])
    responses.add(responses.GET, f"{BASE}/API/system/session/unusedid", json={"user_id": "1"})
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/{tarea_id}", status=200)
    responses.add(responses.POST, f"{BASE}/API/bpm/userTask/{tarea_id}/execution", status=200)


def _tarea_completada_id(tarea_id="42"):
    return any(
        urlparse(c.request.url).path.endswith(f"/userTask/{tarea_id}/execution")
        for c in responses.calls
    )


@responses.activate
def test_coordinador_completa_monitoreo(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _mock_tarea_bonita(TAREA_MONITOREAR)
    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/monitoreo")
    assert r.status_code == 200
    assert r.json()["monitoreo_completado"] is True
    assert _tarea_completada_id()


@responses.activate
def test_monitoreo_idempotente(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _mock_tarea_bonita(TAREA_MONITOREAR)
    c = login("coordinador.regional")
    c.post(f"/api/emergencias/{emergencia_id}/monitoreo")
    # segundo intento: monitoreo_completado ya es True, no va a Bonita
    r = c.post(f"/api/emergencias/{emergencia_id}/monitoreo")
    assert r.status_code == 200


def test_monitoreo_solo_coordinador(login, en_ejecucion):
    for usuario in ("operador.municipal", "ong.cruzroja", "auditor"):
        r = login(usuario).post(f"/api/emergencias/{en_ejecucion}/monitoreo")
        assert r.status_code == 403, usuario


def test_monitoreo_requiere_en_ejecucion(login, seeded, en_ejecucion):
    with seeded() as s:
        e = s.get(Emergencia, en_ejecucion)
        e.estado = EstadoEmergencia.ADJUDICACION
        s.commit()
    r = login("coordinador.regional").post(f"/api/emergencias/{en_ejecucion}/monitoreo")
    assert r.status_code == 409


# ─── finalizar oferta ──────────────────────────────────────────────────────────

def _habilitar_monitoreo(seeded, emergencia_id):
    with seeded() as s:
        e = s.get(Emergencia, emergencia_id)
        e.monitoreo_completado = True
        s.commit()


@responses.activate
def test_ong_adjudicada_finaliza_su_oferta(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _habilitar_monitoreo(seeded, emergencia_id)
    _mock_tarea_bonita(TAREA_CONFIRMAR)
    r = login("ong.cruzroja").post(f"/api/emergencias/{emergencia_id}/finalizar")
    assert r.status_code == 200

    with seeded() as s:
        cruz = s.query(Ong).filter_by(cuit=CRUZ_ROJA).one()
        oferta = s.scalar(select(Oferta).where(Oferta.emergencia_id == emergencia_id, Oferta.ong_id == cruz.id))
        assert oferta.estado is EstadoOferta.FINALIZADA


def test_finalizar_requiere_monitoreo_previo(login, seeded, en_ejecucion):
    # monitoreo_completado sigue en False
    r = login("ong.cruzroja").post(f"/api/emergencias/{en_ejecucion}/finalizar")
    assert r.status_code == 409


def test_finalizar_solo_para_ong_adjudicada(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _habilitar_monitoreo(seeded, emergencia_id)
    # Bomberos tiene oferta NO_ADJUDICADA: no puede finalizar
    r = login("ong.bomberos").post(f"/api/emergencias/{emergencia_id}/finalizar")
    assert r.status_code == 409


def test_finalizar_solo_rol_ong(login, en_ejecucion):
    for usuario in ("coordinador.regional", "operador.municipal", "auditor"):
        r = login(usuario).post(f"/api/emergencias/{en_ejecucion}/finalizar")
        assert r.status_code == 403, usuario


@responses.activate
def test_finalizar_idempotente(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _habilitar_monitoreo(seeded, emergencia_id)
    _mock_tarea_bonita(TAREA_CONFIRMAR)
    c = login("ong.cruzroja")
    c.post(f"/api/emergencias/{emergencia_id}/finalizar")
    # segundo intento
    r = c.post(f"/api/emergencias/{emergencia_id}/finalizar")
    assert r.status_code == 200


# ─── validar cierre ────────────────────────────────────────────────────────────

def _finalizar_todas(seeded, emergencia_id):
    """Pone todas las ofertas adjudicadas en FINALIZADA directamente."""
    with seeded() as s:
        ofertas = s.scalars(
            select(Oferta).where(Oferta.emergencia_id == emergencia_id, Oferta.estado == EstadoOferta.ADJUDICADA)
        ).all()
        for o in ofertas:
            o.estado = EstadoOferta.FINALIZADA
        s.commit()


@responses.activate
def test_coordinador_valida_cierre_cuando_todas_finalizaron(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    _habilitar_monitoreo(seeded, emergencia_id)
    _finalizar_todas(seeded, emergencia_id)
    _mock_tarea_bonita(TAREA_VALIDAR)
    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/validar-cierre")
    assert r.status_code == 200
    assert _tarea_completada_id()
    # Sigue EN_EJECUCION hasta que Bonita mande el evento CIERRE
    assert r.json()["estado"] == "EN_EJECUCION"


def test_validar_cierre_rechazado_si_no_todas_finalizaron(login, seeded, en_ejecucion):
    emergencia_id = en_ejecucion
    # No finalizamos ninguna
    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/validar-cierre")
    assert r.status_code == 409
    assert "finalizadas" in r.json()["detail"].lower()


def test_validar_cierre_solo_coordinador(login, en_ejecucion):
    for usuario in ("operador.municipal", "ong.cruzroja", "auditor"):
        r = login(usuario).post(f"/api/emergencias/{en_ejecucion}/validar-cierre")
        assert r.status_code == 403, usuario
