"""Alta de emergencia de punta a punta (T-05/T-06/T-07/T-08): POST /api/emergencias,
instanciación en Bonita y completar 'Registrar Emergencia', todo como el operador que la pidió.
Bonita queda simulado con HTTP mockeado (`responses`); no necesita Studio.
"""
from urllib.parse import urlparse

import responses

from app.core.config import get_settings
from app.models import Emergencia, Gravedad, Usuario

BASE = get_settings().bonita_base_url
BASE_PATH = urlparse(BASE).path  # "/bonita"


def _mock_alta_ok(case_id="4242", task_id="9001"):
    # un solo login, como el operador que hizo el alta: instancia y completa la tarea él mismo
    responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                  headers={"Set-Cookie": "X-Bonita-API-Token=tok-muni; Path=/"})
    responses.add(responses.GET, f"{BASE}/API/bpm/process", json=[{"id": "555"}])
    responses.add(responses.POST, f"{BASE}/API/bpm/process/555/instantiation", json={"caseId": case_id})
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask",
                  json=[{"id": task_id, "displayName": "Registrar Emergencia"}])
    responses.add(responses.GET, f"{BASE}/API/system/session/unusedid", json={"user_id": "77"})
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/{task_id}", status=200)
    responses.add(responses.POST, f"{BASE}/API/bpm/userTask/{task_id}/execution", status=200)


DATOS = {"tipo": "inundacion", "nivel_gravedad": "ALTO", "zona_afectada": "Centro",
         "descripcion": "Río desbordado"}
ALTA = "/api/emergencias"


def test_solo_municipio_da_de_alta(login):
    for usuario in ("coordinador.regional", "ong.cruzroja", "auditor"):
        assert login(usuario).post(ALTA, json=DATOS).status_code == 403, usuario


@responses.activate
def test_alta_crea_emergencia_instancia_y_completa_registrar(login, seeded):
    _mock_alta_ok(case_id="4242")
    c = login("operador.municipal")
    r = c.post(ALTA, json=DATOS)

    with seeded() as s:
        e = s.query(Emergencia).one()
        assert r.status_code == 201
        assert r.json()["id"] == e.id and r.json()["bonita_case_id"] == 4242
        assert c.get(f"/api/emergencias/{e.id}").json()["bonita_case_id"] == 4242
        assert e.tipo == "inundacion"
        assert e.nivel_gravedad.value == "ALTO"
        assert e.bonita_case_id == 4242
        assert e.municipio_id is not None
        assert e.estado.value == "REGISTRADA"

    # las 7 llamadas HTTP se hicieron en el orden esperado, todas con la misma sesión
    paths = [urlparse(c.request.url).path[len(BASE_PATH):] for c in responses.calls]
    assert paths == [
        "/loginservice", "/API/bpm/process", "/API/bpm/process/555/instantiation",
        "/API/bpm/humanTask", "/API/system/session/unusedid",
        "/API/bpm/userTask/9001", "/API/bpm/userTask/9001/execution",
    ]


@responses.activate
def test_alta_limpia_la_asociacion_bonita_obsoleta_si_reutiliza_case_id(login, seeded):
    case_id = "4242"
    with seeded() as s:
        operador = s.query(Usuario).filter_by(username="operador.municipal").one()
        anterior = Emergencia(
            municipio_id=operador.municipio_id,
            tipo="inundacion",
            nivel_gravedad=Gravedad.ALTO,
            zona_afectada="Centro",
            descripcion="Emergencia anterior",
            bonita_case_id=int(case_id),
        )
        s.add(anterior)
        s.commit()
        emergencia_nueva_id = anterior.id + 1

    _mock_alta_ok(case_id=case_id)
    responses.add(
        responses.GET,
        f"{BASE}/API/bpm/caseVariable",
        json=[{"name": "emergenciaId", "value": str(emergencia_nueva_id)}],
    )

    response = login("operador.municipal").post(ALTA, json=DATOS)

    assert response.status_code == 201
    assert response.json()["bonita_case_id"] == int(case_id)
    with seeded() as s:
        emergencias = s.query(Emergencia).order_by(Emergencia.id).all()
        assert len(emergencias) == 2
        assert emergencias[0].bonita_case_id is None
        assert emergencias[1].bonita_case_id == int(case_id)


@responses.activate
def test_alta_no_limpia_asociacion_si_el_caso_no_corresponde_a_la_emergencia(login, seeded):
    case_id = "4242"
    with seeded() as s:
        operador = s.query(Usuario).filter_by(username="operador.municipal").one()
        s.add(Emergencia(
            municipio_id=operador.municipio_id,
            tipo="inundacion",
            nivel_gravedad=Gravedad.ALTO,
            zona_afectada="Centro",
            descripcion="Emergencia anterior",
            bonita_case_id=int(case_id),
        ))
        s.commit()

    _mock_alta_ok(case_id=case_id)
    responses.add(
        responses.GET,
        f"{BASE}/API/bpm/caseVariable",
        json=[{"name": "emergenciaId", "value": "9999"}],
    )
    responses.add(responses.DELETE, f"{BASE}/API/bpm/case/{case_id}", status=200)

    response = login("operador.municipal").post(ALTA, json=DATOS)

    assert response.status_code == 502
    with seeded() as s:
        emergencias = s.query(Emergencia).all()
        assert len(emergencias) == 1
        assert emergencias[0].bonita_case_id == int(case_id)


@responses.activate
def test_el_alta_se_hace_con_el_usuario_que_la_pidio_y_no_con_el_tecnico(login, seeded):
    """Bonita registra iniciador y ejecutor: cada operador tiene que figurar con su nombre."""
    _mock_alta_ok()
    login("operador.municipal2").post(ALTA, json=DATOS)

    logins = [c.request.body for c in responses.calls if c.request.url.endswith("/loginservice")]
    assert len(logins) == 1
    assert "username=operador.municipal2" in logins[0]
    assert "walter.bates" not in logins[0]


@responses.activate
def test_si_bonita_rechaza_el_login_no_queda_emergencia_a_medias(login, seeded):
    responses.add(responses.POST, f"{BASE}/loginservice", status=401)
    r = login("operador.municipal").post(ALTA, json=DATOS)

    assert r.status_code == 502
    assert "no se pudo" in r.json()["detail"].lower()
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


@responses.activate
def test_si_bonita_no_responde_a_tiempo_no_queda_emergencia_a_medias(login, seeded):
    import requests

    responses.add(responses.POST, f"{BASE}/loginservice", body=requests.ConnectTimeout())
    r = login("operador.municipal").post(ALTA, json=DATOS)

    assert r.status_code == 502
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


def _mock_caso_sin_tarea(case_id="1"):
    """El caso se crea pero 'Registrar Emergencia' nunca aparece."""
    responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                  headers={"Set-Cookie": "X-Bonita-API-Token=tok; Path=/"})
    responses.add(responses.GET, f"{BASE}/API/bpm/process", json=[{"id": "555"}])
    responses.add(responses.POST, f"{BASE}/API/bpm/process/555/instantiation", json={"caseId": case_id})
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[])


@responses.activate
def test_si_no_aparece_la_tarea_registrar_no_queda_emergencia_a_medias(login, seeded):
    _mock_caso_sin_tarea()
    responses.add(responses.DELETE, f"{BASE}/API/bpm/case/1", status=200)

    r = login("operador.municipal").post(ALTA, json=DATOS)

    assert r.status_code == 502
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


@responses.activate
def test_si_el_alta_falla_despues_de_crear_el_caso_se_borra_en_bonita(login, seeded):
    """Sin esto quedaba un caso huérfano trabado en 'Registrar Emergencia' (visto en Studio el 12/10),
    con un emergenciaId que SQLite reusa para la emergencia siguiente."""
    _mock_caso_sin_tarea(case_id="77")
    responses.add(responses.DELETE, f"{BASE}/API/bpm/case/77", status=200)

    login("operador.municipal").post(ALTA, json=DATOS)

    borrados = [c for c in responses.calls if c.request.method == "DELETE"]
    assert [urlparse(c.request.url).path[len(BASE_PATH):] for c in borrados] == ["/API/bpm/case/77"]
    # lo borra el usuario técnico: un operador no tiene permiso para borrar casos
    logins = [c.request.body for c in responses.calls if c.request.url.endswith("/loginservice")]
    assert "username=walter.bates" in logins[-1]


@responses.activate
def test_si_tampoco_se_puede_borrar_el_caso_la_respuesta_es_la_misma(login, seeded):
    _mock_caso_sin_tarea()
    responses.add(responses.DELETE, f"{BASE}/API/bpm/case/1", status=500)

    r = login("operador.municipal").post(ALTA, json=DATOS)

    assert r.status_code == 502 and "probá de nuevo" in r.json()["detail"]
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


@responses.activate
def test_si_falla_antes_de_crear_el_caso_no_se_borra_nada(login, seeded):
    responses.add(responses.POST, f"{BASE}/loginservice", status=401)
    login("operador.municipal").post(ALTA, json=DATOS)
    assert not [c for c in responses.calls if c.request.method == "DELETE"]


def _campos_con_error(r) -> set[str]:
    return {e["loc"][-1] for e in r.json()["detail"]}


def test_gravedad_invalida_se_rechaza_sin_llamar_a_bonita(login):
    r = login("operador.municipal").post(ALTA, json={**DATOS, "nivel_gravedad": "CATACLISMO"})
    assert r.status_code == 422 and _campos_con_error(r) == {"nivel_gravedad"}


def test_campos_vacios_se_rechazan_sin_llamar_a_bonita(login):
    r = login("operador.municipal").post(ALTA, json={**DATOS, "zona_afectada": "   "})
    assert r.status_code == 422 and _campos_con_error(r) == {"zona_afectada"}


def test_zona_demasiado_larga_se_rechaza_sin_llamar_a_bonita(login):
    r = login("operador.municipal").post(ALTA, json={**DATOS, "zona_afectada": "x" * 201})
    assert r.status_code == 422 and _campos_con_error(r) == {"zona_afectada"}


def test_varios_errores_se_informan_juntos(login):
    r = login("operador.municipal").post(ALTA, json={**DATOS, "zona_afectada": "", "nivel_gravedad": "X"})
    assert r.status_code == 422
    assert _campos_con_error(r) == {"zona_afectada", "nivel_gravedad"}


@responses.activate
def test_los_espacios_de_los_bordes_no_se_guardan(login, seeded):
    _mock_alta_ok()
    login("operador.municipal").post(ALTA, json={**DATOS, "zona_afectada": "  Centro  "})
    with seeded() as s:
        assert s.query(Emergencia).one().zona_afectada == "Centro"


def test_usuario_municipio_sin_municipio_asignado_no_rompe(login, seeded):
    from app.core.security import hash_password
    from app.models import Rol, Usuario

    with seeded() as s:
        s.add(Usuario(username="sin.municipio", password_hash=hash_password("demo1234"),
                      nombre="Sin Municipio", rol=Rol.MUNICIPIO))
        s.commit()

    from app.seed import DEMO_PASSWORD

    c = login("operador.municipal")  # ya logueado; nos volvemos a loguear con el otro usuario
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "sin.municipio", "password": DEMO_PASSWORD})
    assert r.status_code == 200
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    r = c.post(ALTA, json=DATOS)
    assert r.status_code == 502
    with seeded() as s:
        assert s.query(Emergencia).count() == 0
