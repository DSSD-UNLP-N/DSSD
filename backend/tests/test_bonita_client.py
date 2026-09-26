"""Cliente de Bonita con HTTP simulado: no necesita Studio corriendo."""
import pytest
import requests
import responses

from app.integrations.bonita import BonitaClient, BonitaError, CONTRACT_INPUTS

BASE = "http://bonita.test/bonita"
CONTRATO = {"emergenciaId": 1, "municipioId": 2, "nivelGravedad": "ALTO",
            "ventanaOfertasISO": "2026-10-01T10:00:00-03:00"}


@pytest.fixture
def client():
    return BonitaClient(BASE + "/")  # con barra final: debe normalizarse


def _login_ok(rsps):
    rsps.add(responses.POST, f"{BASE}/loginservice", status=204,
             headers={"Set-Cookie": "X-Bonita-API-Token=tok123; Path=/"})


@responses.activate
def test_login_guarda_el_token_csrf_como_header(client):
    _login_ok(responses)
    client.login("walter.bates", "bpm")
    assert client.session.headers["X-Bonita-API-Token"] == "tok123"
    body = responses.calls[0].request.body
    assert "redirect=false" in body and "username=walter.bates" in body


@responses.activate
def test_login_sin_cookie_de_token_falla(client):
    responses.add(responses.POST, f"{BASE}/loginservice", status=204)
    with pytest.raises(BonitaError):
        client.login("u", "p")


@responses.activate
def test_login_rechazado_propaga_error_http(client):
    responses.add(responses.POST, f"{BASE}/loginservice", status=401)
    with pytest.raises(Exception):
        client.login("u", "mal")


@responses.activate
def test_resolve_process_id(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/process", json=[{"id": "555"}])
    assert client.resolve_process_id("Gestion Integral de la Emergencia", "1.0") == "555"
    q = responses.calls[0].request.url
    assert "name%3DGestion" in q or "name=Gestion" in q
    assert "version" in q


@responses.activate
def test_resolve_process_no_desplegado(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/process", json=[])
    with pytest.raises(BonitaError, match="desplegado"):
        client.resolve_process_id("X", "1.0")


def test_start_case_exige_los_4_inputs_del_contrato(client):
    for faltante in CONTRACT_INPUTS:
        incompleto = {k: v for k, v in CONTRATO.items() if k != faltante}
        with pytest.raises(ValueError, match=faltante):
            client.start_case("555", incompleto)


@responses.activate
def test_start_case_envia_el_contrato_y_devuelve_case_id(client):
    responses.add(responses.POST, f"{BASE}/API/bpm/process/555/instantiation", json={"caseId": "1001"})
    assert client.start_case("555", CONTRATO) == "1001"
    import json
    assert json.loads(responses.calls[0].request.body) == CONTRATO


@responses.activate
def test_set_case_variable_envia_valor_y_tipo(client):
    import json
    responses.add(responses.PUT, f"{BASE}/API/bpm/caseVariable/1001/ventanaOfertasISO", status=200)
    client.set_case_variable("1001", "ventanaOfertasISO", "2026-10-02T00:00:00-03:00", "java.lang.String")
    assert json.loads(responses.calls[0].request.body) == {
        "value": "2026-10-02T00:00:00-03:00", "type": "java.lang.String"}


@responses.activate
def test_get_case_variables_devuelve_nombre_a_valor(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/caseVariable",
                  json=[{"name": "emergenciaId", "value": "7"},
                        {"name": "ventanaOfertasISO", "value": "2026-10-01T10:00:00-03:00"}])
    assert client.get_case_variables("1001") == {
        "emergenciaId": "7", "ventanaOfertasISO": "2026-10-01T10:00:00-03:00"}
    assert "case_id%3D1001" in responses.calls[0].request.url or "case_id=1001" in responses.calls[0].request.url


@responses.activate
def test_get_human_tasks_pide_la_pagina_completa(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[{"displayName": "Registrar Emergencia"}])
    assert client.get_human_tasks("1001")[0]["displayName"] == "Registrar Emergencia"
    assert "p=0" in responses.calls[0].request.url and "c=100" in responses.calls[0].request.url


@responses.activate
def test_get_case_devuelve_quien_inicio_el_caso(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/case/1001", json={"id": "1001", "started_by": "101"})
    assert client.get_case("1001")["started_by"] == "101"


@responses.activate
def test_get_archived_human_tasks_trae_el_ejecutor(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/archivedHumanTask",
                  json=[{"displayName": "Registrar Emergencia", "executedBy": "101"}])
    assert client.get_archived_human_tasks("1001")[0]["executedBy"] == "101"
    assert "p=0" in responses.calls[0].request.url and "c=100" in responses.calls[0].request.url


@responses.activate
def test_user_name_resuelve_el_id_numerico(client):
    responses.add(responses.GET, f"{BASE}/API/identity/user/101", json={"id": "101", "userName": "operador.municipal"})
    assert client.user_name("101") == "operador.municipal"


@responses.activate
def test_wait_for_task_reintenta_hasta_que_la_tarea_aparece(client):
    """Bonita crea la tarea siguiente con un instante de retraso."""
    url = f"{BASE}/API/bpm/humanTask"
    responses.add(responses.GET, url, json=[])
    responses.add(responses.GET, url, json=[{"id": "9", "displayName": "Publicar Convocatoria y Notificar"}])
    assert client.wait_for_task("1001", "Publicar Convocatoria")["id"] == "9"
    assert len(responses.calls) == 2


@responses.activate
def test_wait_for_task_devuelve_none_si_nunca_aparece(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[])
    assert client.wait_for_task("1001", "Publicar Convocatoria", retries=3) is None
    assert len(responses.calls) == 3


@responses.activate
def test_find_task_busca_por_prefijo_del_nombre(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask",
                  json=[{"id": "1", "displayName": "Cargar Ofertas de Ayuda"},
                        {"id": "2", "displayName": "Registrar Emergencia"}])
    tarea = client.find_task("1001", "Registrar Emergencia")
    assert tarea == {"id": "2", "displayName": "Registrar Emergencia"}


@responses.activate
def test_find_task_devuelve_none_si_no_esta(client):
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[])
    assert client.find_task("1001", "Registrar Emergencia") is None


@responses.activate
def test_complete_task_as_self_asigna_y_ejecuta(client):
    import json

    responses.add(responses.GET, f"{BASE}/API/system/session/unusedid", json={"user_id": "77"})
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/9001", status=200)
    responses.add(responses.POST, f"{BASE}/API/bpm/userTask/9001/execution", status=200)

    client.complete_task_as_self("9001")

    assign_call, exec_call = responses.calls[1], responses.calls[2]
    assert json.loads(assign_call.request.body) == {"assigned_id": "77"}
    assert exec_call.request.url.endswith("/userTask/9001/execution")


def test_todas_las_llamadas_llevan_timeout(monkeypatch):
    c = BonitaClient(BASE, timeout=2.5)
    timeouts = []

    def fake_request(method, url, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        raise requests.ConnectTimeout()

    monkeypatch.setattr(c.session, "request", fake_request)
    llamadas = [
        lambda: c.login("u", "p"),
        lambda: c.resolve_process_id("X", "1.0"),
        lambda: c.start_case("555", CONTRATO),
        lambda: c.set_case_variable("1", "v", "x", "java.lang.String"),
        lambda: c.get_human_tasks("1"),
        lambda: c.get_case_variables("1"),
        lambda: c.current_user_id(),
        lambda: c.assign_task("1", "2"),
        lambda: c.execute_task("1"),
        lambda: c.get_case("1"),
        lambda: c.get_archived_human_tasks("1"),
        lambda: c.user_name("101"),
    ]
    for llamada in llamadas:
        with pytest.raises(requests.ConnectTimeout):
            llamada()
    assert timeouts == [2.5] * len(llamadas)


@responses.activate
def test_assign_task_propaga_error_http(client):
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/9001", status=500)
    with pytest.raises(Exception):
        client.assign_task("9001", "77")
