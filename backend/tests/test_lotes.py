"""T-10: lotes de necesidades y publicación de la convocatoria, por la API que usa la SPA.
Bonita va mockeado (`responses`); la secuencia real se prueba en test_bonita_integration.py.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
import responses

from app.core.config import get_settings
from app.models import Emergencia, EstadoEmergencia, Gravedad, Lote, Municipio, TipoLote

BASE = get_settings().bonita_base_url
BASE_PATH = urlparse(BASE).path
CASE = 4242
LOTE = {"recurso": "Paramédicos", "cantidad": 5, "unidad": "personas", "tipo": "PRINCIPAL"}


def _futuro(horas=48):
    return (datetime.now().astimezone() + timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture
def emergencia(seeded):
    with seeded() as s:
        municipio = s.query(Municipio).one()
        e = Emergencia(municipio_id=municipio.id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO,
                       zona_afectada="Centro", descripcion="Río desbordado", bonita_case_id=CASE)
        s.add(e)
        s.commit()
        return e.id


def _con_lote(seeded, emergencia_id, **kwargs):
    with seeded() as s:
        s.add(Lote(emergencia_id=emergencia_id, recurso="Agua", cantidad=100, unidad="litros", **kwargs))
        s.commit()


def _mock_publicacion(revisar_pendiente=True):
    """Dos logins (admin y coordinador), las tareas del caso y el seteo de la ventana."""
    for token in ("tok-admin", "tok-coord"):
        responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                      headers={"Set-Cookie": f"X-Bonita-API-Token={token}; Path=/"})
    url_tareas = f"{BASE}/API/bpm/humanTask"
    if revisar_pendiente:
        responses.add(responses.GET, url_tareas, json=[{"id": "1", "displayName": "Revisar Informacion y Generar Lotes de Necesidades"}])
    responses.add(responses.GET, url_tareas, json=[{"id": "2", "displayName": "Publicar Convocatoria y Notificar a la Red de ONGs"}])
    responses.add(responses.GET, f"{BASE}/API/system/session/unusedid", json={"user_id": "77"})
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/1", status=200)
    responses.add(responses.POST, f"{BASE}/API/bpm/userTask/1/execution", status=200)
    responses.add(responses.PUT, f"{BASE}/API/bpm/caseVariable/{CASE}/ventanaOfertasISO", status=200)
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/2", status=200)
    responses.add(responses.POST, f"{BASE}/API/bpm/userTask/2/execution", status=200)


def _paths():
    return [urlparse(c.request.url).path[len(BASE_PATH):] for c in responses.calls]


def _lotes(emergencia):
    return f"/api/emergencias/{emergencia}/lotes"


def _publicar(emergencia):
    return f"/api/emergencias/{emergencia}/publicar"


# --- lotes ---------------------------------------------------------------

def test_solo_el_coordinador_gestiona_lotes(login, emergencia):
    for usuario in ["operador.municipal", "ong.cruzroja", "auditor"]:
        r = login(usuario).post(_lotes(emergencia), json=LOTE)
        assert r.status_code == 403, usuario


def test_agregar_lote_y_verlo_en_el_detalle(login, emergencia, seeded):
    c = login("coordinador.regional")
    r = c.post(_lotes(emergencia), json=LOTE)
    assert r.status_code == 201 and r.json()["recurso"] == "Paramédicos"
    with seeded() as s:
        lote = s.query(Lote).one()
        assert (lote.recurso, lote.cantidad, lote.unidad, lote.tipo) == ("Paramédicos", 5, "personas", TipoLote.PRINCIPAL)
    detalle = c.get(f"/api/emergencias/{emergencia}").json()
    assert [(l["recurso"], l["cantidad"], l["unidad"]) for l in detalle["lotes"]] == [("Paramédicos", 5, "personas")]


def test_lote_de_apoyo(login, emergencia, seeded):
    login("coordinador.regional").post(_lotes(emergencia), json={**LOTE, "tipo": "APOYO"})
    with seeded() as s:
        assert s.query(Lote).one().tipo is TipoLote.APOYO


@pytest.mark.parametrize("campo,valor", [
    ("recurso", "   "),
    ("recurso", ""),
    ("cantidad", 0),
    ("cantidad", "dos"),
    ("unidad", ""),
    ("unidad", "   "),
    ("tipo", "SECUNDARIO"),
])
def test_datos_invalidos_no_crean_lote(login, emergencia, seeded, campo, valor):
    r = login("coordinador.regional").post(_lotes(emergencia), json={**LOTE, campo: valor})
    assert r.status_code == 422, r.text
    with seeded() as s:
        assert s.query(Lote).count() == 0


def test_borrar_lote(login, emergencia, seeded):
    _con_lote(seeded, emergencia)
    with seeded() as s:
        lote_id = s.query(Lote).one().id
    r = login("coordinador.regional").delete(f"{_lotes(emergencia)}/{lote_id}")
    assert r.status_code == 204
    with seeded() as s:
        assert s.query(Lote).count() == 0


def test_no_se_puede_borrar_un_lote_de_otra_emergencia(login, emergencia, seeded):
    r = login("coordinador.regional").delete(f"{_lotes(emergencia)}/999")
    assert r.status_code == 400 and "no pertenece a esta emergencia" in r.json()["detail"]


def test_emergencia_inexistente_da_404(login):
    assert login("coordinador.regional").post(_lotes(999), json=LOTE).status_code == 404


# --- publicación ---------------------------------------------------------

@responses.activate
def test_publicar_completa_las_dos_tareas_y_setea_la_ventana(login, emergencia, seeded):
    _con_lote(seeded, emergencia)
    _mock_publicacion()
    ventana = _futuro()
    c = login("coordinador.regional")
    r = c.post(_publicar(emergencia), json={"ventana_fin": ventana})

    assert r.status_code == 200 and r.json()["estado"] == "CONVOCATORIA"
    with seeded() as s:
        e = s.get(Emergencia, emergencia)
        assert e.estado is EstadoEmergencia.CONVOCATORIA
        # se guarda en UTC; se muestra en hora local (la que eligió el Coordinador)
        guardada = e.ventana_ofertas_fin.replace(tzinfo=timezone.utc).astimezone()
        assert guardada.strftime("%Y-%m-%dT%H:%M") == ventana
    detalle = c.get(f"/api/emergencias/{emergencia}").json()
    assert detalle["estado"] == "CONVOCATORIA"
    assert datetime.fromisoformat(detalle["ventana_ofertas_fin"]).astimezone().strftime("%Y-%m-%dT%H:%M") == ventana

    # la ventana se setea ANTES de completar "Publicar…": el timer la lee al activarse la tarea siguiente
    assert _paths() == [
        "/loginservice", "/loginservice", "/API/bpm/humanTask",
        "/API/system/session/unusedid", "/API/bpm/userTask/1", "/API/bpm/userTask/1/execution",
        "/API/bpm/humanTask", f"/API/bpm/caseVariable/{CASE}/ventanaOfertasISO",
        "/API/system/session/unusedid", "/API/bpm/userTask/2", "/API/bpm/userTask/2/execution",
    ]
    enviado = json.loads(next(c.request.body for c in responses.calls if "caseVariable" in c.request.url))
    assert enviado["type"] == "java.lang.String" and enviado["value"].startswith(ventana)


@responses.activate
def test_las_tareas_del_coordinador_las_ejecuta_el_coordinador_que_publica(login, emergencia, seeded):
    """Bonita registra al ejecutor: tiene que ser quien publicó, y el técnico solo lee y setea variables."""
    _con_lote(seeded, emergencia)
    _mock_publicacion()
    login("coordinador.regional").post(_publicar(emergencia), json={"ventana_fin": _futuro()})

    logins = [c.request.body for c in responses.calls if c.request.url.endswith("/loginservice")]
    assert len(logins) == 2
    assert "username=walter.bates" in logins[0]
    assert "username=coordinador.regional" in logins[1]


@responses.activate
def test_reintento_cuando_revisar_ya_estaba_completada(login, emergencia, seeded):
    """Si un intento anterior se cortó en el medio, publicar de nuevo sigue desde 'Publicar…'."""
    _con_lote(seeded, emergencia)
    _mock_publicacion(revisar_pendiente=False)
    r = login("coordinador.regional").post(_publicar(emergencia), json={"ventana_fin": _futuro()})
    assert r.status_code == 200
    with seeded() as s:
        assert s.get(Emergencia, emergencia).estado is EstadoEmergencia.CONVOCATORIA
    assert "/API/bpm/userTask/1/execution" not in _paths()


def test_no_se_publica_sin_lotes(login, emergencia, seeded):
    r = login("coordinador.regional").post(_publicar(emergencia), json={"ventana_fin": _futuro()})
    assert r.status_code == 400 and "al menos un lote" in r.json()["detail"]
    with seeded() as s:
        assert s.get(Emergencia, emergencia).estado is EstadoEmergencia.REGISTRADA


@pytest.mark.parametrize("ventana,status,mensaje", [
    ("", 422, None),
    ("no es fecha", 422, None),
    ("2020-01-01T10:00", 400, "fecha futura"),
])
def test_ventana_invalida_o_pasada_no_publica(login, emergencia, seeded, ventana, status, mensaje):
    _con_lote(seeded, emergencia)
    r = login("coordinador.regional").post(_publicar(emergencia), json={"ventana_fin": ventana})
    assert r.status_code == status, r.text
    if mensaje:
        assert mensaje in r.json()["detail"]
    with seeded() as s:
        assert s.get(Emergencia, emergencia).estado is EstadoEmergencia.REGISTRADA


@responses.activate
def test_si_bonita_falla_la_emergencia_queda_sin_publicar(login, emergencia, seeded):
    _con_lote(seeded, emergencia)
    responses.add(responses.POST, f"{BASE}/loginservice", status=500)
    r = login("coordinador.regional").post(_publicar(emergencia), json={"ventana_fin": _futuro()})
    assert r.status_code == 400 and "No se pudo publicar" in r.json()["detail"]
    with seeded() as s:
        e = s.get(Emergencia, emergencia)
        assert e.estado is EstadoEmergencia.REGISTRADA and e.ventana_ofertas_fin is None


@responses.activate
def test_publicada_no_se_puede_republicar_ni_tocar_los_lotes(login, emergencia, seeded):
    _con_lote(seeded, emergencia)
    _mock_publicacion()
    c = login("coordinador.regional")
    c.post(_publicar(emergencia), json={"ventana_fin": _futuro()})

    r = c.post(_publicar(emergencia), json={"ventana_fin": _futuro()})
    assert r.status_code == 400 and "ya fue publicada" in r.json()["detail"]
    r = c.post(_lotes(emergencia), json=LOTE)
    assert r.status_code == 400 and "no se pueden modificar" in r.json()["detail"]


@responses.activate
def test_al_publicar_las_ongs_ven_la_emergencia(login, emergencia, seeded):
    _con_lote(seeded, emergencia)
    _mock_publicacion()
    login("coordinador.regional").post(_publicar(emergencia), json={"ventana_fin": _futuro()})

    ong = login("ong.cruzroja")
    assert ong.get("/api/emergencias").status_code == 403
    assert ong.get(f"/api/emergencias/{emergencia}").json()["estado"] == "CONVOCATORIA"
