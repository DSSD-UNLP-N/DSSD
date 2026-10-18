"""Listado y detalle de emergencias por la API: qué ve cada perfil."""
from datetime import datetime, timezone

import pytest
import responses

from app.core.config import get_settings
from app.models import Emergencia, EstadoEmergencia, Gravedad, Lote, Municipio, TipoLote

BASE = get_settings().bonita_base_url


@pytest.fixture
def emergencias(seeded):
    """Una emergencia del municipio del seed (registrada) y otra de otro municipio (en convocatoria)."""
    with seeded() as s:
        propio = s.query(Municipio).one()
        otro = Municipio(nombre="Tres Arroyos", provincia="Buenos Aires")
        s.add(otro)
        s.flush()
        propia = Emergencia(municipio_id=propio.id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO,
                            zona_afectada="Centro", descripcion="Río desbordado", bonita_case_id=11,
                            creada_en=datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc))
        ajena = Emergencia(municipio_id=otro.id, tipo="incendio", nivel_gravedad=Gravedad.CRITICO,
                           zona_afectada="Sierra", descripcion="Foco activo", bonita_case_id=12,
                           estado=EstadoEmergencia.CONVOCATORIA)
        ajena.lotes = [Lote(recurso="Brigadistas", cantidad=20, unidad="personas", tipo=TipoLote.APOYO)]
        s.add_all([propia, ajena])
        s.commit()
        return propia.id, ajena.id


def _ids(c):
    return [e["id"] for e in c.get("/api/emergencias").json()]


def test_listado_exige_sesion(client):
    assert client.get("/api/emergencias").status_code == 401


def test_municipio_ve_solo_las_de_su_municipio(login, emergencias):
    propia, ajena = emergencias
    c = login("operador.municipal")
    assert _ids(c) == [propia]
    assert c.get(f"/api/emergencias/{ajena}").status_code == 404


@pytest.mark.parametrize("usuario", ["coordinador.regional", "auditor"])
def test_coordinador_y_auditor_ven_todas(login, emergencias, usuario):
    c = login(usuario)
    assert set(_ids(c)) == set(emergencias)
    for eid in emergencias:
        assert c.get(f"/api/emergencias/{eid}").status_code == 200


def test_ong_ve_solo_convocatorias_abiertas(login, emergencias):
    propia, ajena = emergencias
    c = login("ong.bomberos")
    assert _ids(c) == [ajena]
    assert c.get(f"/api/emergencias/{propia}").status_code == 404


def test_detalle_muestra_datos_caso_y_lotes(login, emergencias):
    _, ajena = emergencias
    d = login("coordinador.regional").get(f"/api/emergencias/{ajena}").json()
    assert (d["municipio_nombre"], d["descripcion"], d["bonita_case_id"]) == ("Tres Arroyos", "Foco activo", 12)
    assert [(l["recurso"], l["cantidad"], l["unidad"], l["tipo"]) for l in d["lotes"]] == [
        ("Brigadistas", 20, "personas", "APOYO")]
    assert d["estado"] == "CONVOCATORIA"


def test_las_fechas_salen_con_zona_utc(login, emergencias):
    """La SPA las convierte a hora local: sin la 'Z' (o el offset) las leería como locales."""
    propia, _ = emergencias
    d = login("operador.municipal").get(f"/api/emergencias/{propia}").json()
    assert d["creada_en"].endswith(("Z", "+00:00"))


def test_emergencia_inexistente_da_404(login):
    r = login("coordinador.regional").get("/api/emergencias/999")
    assert r.status_code == 404 and "no encontrada" in r.json()["detail"]


# --- tarea pendiente de Bonita, mostrada a la ONG en la SPA (GET /api/emergencias/{id}) ---


def _mock_login_y_tarea(tarea: dict | None):
    responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                  headers={"Set-Cookie": "X-Bonita-API-Token=tok; Path=/"})
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[tarea] if tarea else [])


@responses.activate
def test_ong_ve_su_tarea_pendiente_en_bonita(login, emergencias):
    _, ajena = emergencias
    _mock_login_y_tarea({"id": "1", "displayName": "Cargar Ofertas de Ayuda"})

    r = login("ong.bomberos").get(f"/api/emergencias/{ajena}")

    assert r.json()["tarea_bonita"] == "Cargar Ofertas de Ayuda"
    login_call = next(c for c in responses.calls if c.request.url.endswith("/loginservice"))
    assert "username=ong.bomberos" in login_call.request.body


@responses.activate
def test_sin_tarea_pendiente_no_hay_nada_que_mostrar(login, emergencias):
    """Bonita ya cerró la tarea (venció la ventana) o la convocatoria recién arranca."""
    _, ajena = emergencias
    _mock_login_y_tarea(None)

    assert login("ong.bomberos").get(f"/api/emergencias/{ajena}").json()["tarea_bonita"] is None


@responses.activate
def test_si_bonita_no_responde_el_detalle_igual_se_devuelve(login, emergencias):
    _, ajena = emergencias
    responses.add(responses.POST, f"{BASE}/loginservice", status=500)

    r = login("ong.bomberos").get(f"/api/emergencias/{ajena}")

    assert r.status_code == 200 and r.json()["tarea_bonita"] is None


def test_a_otros_perfiles_y_al_listado_no_se_les_consulta_bonita(login, emergencias):
    """Sin @responses.activate: si el código llamara a Bonita, esto fallaría con un error de red."""
    _, ajena = emergencias
    for usuario in ("coordinador.regional", "auditor"):
        r = login(usuario).get(f"/api/emergencias/{ajena}")
        assert r.status_code == 200 and r.json()["tarea_bonita"] is None
    assert login("ong.bomberos").get("/api/emergencias").status_code == 200
