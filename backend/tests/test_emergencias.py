"""Alta de emergencia de punta a punta (T-05/T-06/T-07/T-08): formulario, POST,
instanciación en Bonita y completar 'Registrar Emergencia', todo como el operador que la pidió.
Bonita queda simulado con HTTP mockeado (`responses`); no necesita Studio.
"""
from urllib.parse import urlparse

import responses

from app.core.config import get_settings
from app.models import Emergencia

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


def test_solo_municipio_ve_y_usa_el_formulario(login):
    assert login("coordinador.regional").get("/emergencias/nueva").status_code == 403
    assert login("ong.cruzroja").post("/emergencias/nueva", data=DATOS).status_code == 403
    assert login("operador.municipal").get("/emergencias/nueva").status_code == 200


@responses.activate
def test_alta_crea_emergencia_instancia_y_completa_registrar(login, seeded):
    _mock_alta_ok(case_id="4242")
    c = login("operador.municipal")
    r = c.post("/emergencias/nueva", data=DATOS)

    with seeded() as s:
        e = s.query(Emergencia).one()
        # Post/Redirect/Get: recargar la página de destino no reenvía el formulario
        assert r.status_code == 303
        assert r.headers["location"] == f"/emergencias/{e.id}?nueva=1"
        detalle = c.get(r.headers["location"])
        assert detalle.status_code == 200
        assert "Emergencia registrada" in detalle.text and "#4242" in detalle.text
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
def test_el_alta_se_hace_con_el_usuario_que_la_pidio_y_no_con_el_tecnico(login, seeded):
    """Bonita registra iniciador y ejecutor: cada operador tiene que figurar con su nombre."""
    _mock_alta_ok()
    login("operador.municipal2").post("/emergencias/nueva", data=DATOS)

    logins = [c.request.body for c in responses.calls if c.request.url.endswith("/loginservice")]
    assert len(logins) == 1
    assert "username=operador.municipal2" in logins[0]
    assert "walter.bates" not in logins[0]


@responses.activate
def test_si_bonita_rechaza_el_login_no_queda_emergencia_a_medias(login, seeded):
    responses.add(responses.POST, f"{BASE}/loginservice", status=401)
    r = login("operador.municipal").post("/emergencias/nueva", data=DATOS)

    assert r.status_code == 502
    assert "no se pudo" in r.text.lower()
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


@responses.activate
def test_si_bonita_no_responde_a_tiempo_no_queda_emergencia_a_medias(login, seeded):
    import requests

    responses.add(responses.POST, f"{BASE}/loginservice", body=requests.ConnectTimeout())
    r = login("operador.municipal").post("/emergencias/nueva", data=DATOS)

    assert r.status_code == 502
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


@responses.activate
def test_si_no_aparece_la_tarea_registrar_no_queda_emergencia_a_medias(login, seeded):
    responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                  headers={"Set-Cookie": "X-Bonita-API-Token=tok; Path=/"})
    responses.add(responses.GET, f"{BASE}/API/bpm/process", json=[{"id": "555"}])
    responses.add(responses.POST, f"{BASE}/API/bpm/process/555/instantiation", json={"caseId": "1"})
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[])  # nunca aparece

    r = login("operador.municipal").post("/emergencias/nueva", data=DATOS)

    assert r.status_code == 502
    with seeded() as s:
        assert s.query(Emergencia).count() == 0


def test_gravedad_invalida_se_rechaza_sin_llamar_a_bonita(login):
    r = login("operador.municipal").post("/emergencias/nueva", data={**DATOS, "nivel_gravedad": "CATACLISMO"})
    assert r.status_code == 400
    assert "gravedad" in r.text.lower()


def test_campos_vacios_se_rechazan_sin_llamar_a_bonita(login):
    r = login("operador.municipal").post("/emergencias/nueva", data={**DATOS, "zona_afectada": "   "})
    assert r.status_code == 400


def test_zona_demasiado_larga_se_rechaza_sin_llamar_a_bonita(login):
    r = login("operador.municipal").post("/emergencias/nueva", data={**DATOS, "zona_afectada": "x" * 201})
    assert r.status_code == 400
    assert "Zona afectada: máximo 200 caracteres." in r.text


def test_varios_errores_se_informan_juntos(login):
    r = login("operador.municipal").post(
        "/emergencias/nueva", data={**DATOS, "zona_afectada": "", "nivel_gravedad": "X"})
    assert r.status_code == 400
    assert "Nivel de gravedad: valor inválido." in r.text
    assert "Zona afectada: es obligatorio." in r.text


@responses.activate
def test_los_espacios_de_los_bordes_no_se_guardan(login, seeded):
    _mock_alta_ok()
    login("operador.municipal").post("/emergencias/nueva", data={**DATOS, "zona_afectada": "  Centro  "})
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
    c.post("/logout")
    r = c.post("/login", data={"username": "sin.municipio", "password": DEMO_PASSWORD})
    assert r.status_code == 303

    r = c.post("/emergencias/nueva", data=DATOS)
    assert r.status_code == 502
    with seeded() as s:
        assert s.query(Emergencia).count() == 0
