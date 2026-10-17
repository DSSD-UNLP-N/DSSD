"""Cliente HTTP de la API Nacional, con HTTP simulado (`responses`)."""
import pytest
import requests
import responses

from app.integrations.nacional import (
    NacionalClient,
    NacionalError,
    NacionalLoginEndpointMissing,
    NacionalLoginRejected,
)

BASE = "http://nacional.test"
TIPO = {"codigo": "PARAMEDICO", "nombre": "Paramédico", "categoria": "PERSONAL", "unidad": "personas",
        "certificacion_requerida": "SALUD_PREHOSP"}


@responses.activate
def test_tipos_recurso_devuelve_el_catalogo():
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[TIPO])
    assert NacionalClient(BASE).tipos_recurso() == [TIPO]


@responses.activate
def test_login_a_nacional_y_propaga_el_token_en_llamadas_siguientes():
    responses.add(
        responses.POST,
        f"{BASE}/login",
        json={"access_token": "national-token", "token_type": "bearer"},
    )
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[TIPO])

    client = NacionalClient(BASE)
    result = client.login("ong.cruzroja", "demo1234")
    assert client.tipos_recurso() == [TIPO]

    assert "Authorization" not in responses.calls[0].request.headers
    assert responses.calls[1].request.headers["Authorization"] == "Bearer national-token"


@responses.activate
def test_login_distigue_credenciales_rechazadas_de_endpoint_no_desplegado():
    client = NacionalClient(BASE)
    responses.add(responses.POST, f"{BASE}/login", status=401)
    with pytest.raises(NacionalLoginRejected):
        client.login("usuario", "incorrecta")

    responses.reset()
    responses.add(responses.POST, f"{BASE}/login", status=404)
    with pytest.raises(NacionalLoginEndpointMissing):
        client.login("usuario", "clave")


def test_get_nacional_reutiliza_el_bearer_de_la_llamada_actual():
    from starlette.requests import Request

    from app.core.config import Settings
    from app.integrations.nacional import get_nacional

    request = Request({
        "type": "http",
        "headers": [(b"authorization", b"Bearer usuario-token")],
        "method": "GET",
        "path": "/api/tipos-recurso",
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 80),
        "scheme": "http",
        "http_version": "1.1",
    })

    client = get_nacional(request, Settings(_env_file=None))
    assert client.access_token == "usuario-token"


@responses.activate
def test_la_barra_final_de_la_url_no_molesta():
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[])
    assert NacionalClient(f"{BASE}/").tipos_recurso() == []


@responses.activate
@pytest.mark.parametrize("falla", [
    {"status": 500},
    {"status": 404, "json": {"detail": "no"}},
    {"body": "<html>no soy json</html>"},
    {"body": requests.ConnectionError("sin red")},
    {"body": requests.Timeout("lento")},
])
def test_cualquier_falla_sale_como_nacional_error(falla):
    responses.add(responses.GET, f"{BASE}/tipos-recurso", **falla)
    with pytest.raises(NacionalError):
        NacionalClient(BASE).tipos_recurso()


@responses.activate
def test_validar_manda_la_gravedad_y_los_items_y_devuelve_el_resultado():
    import json

    resultado = {"alcanza_todo": False, "resultados": [{"tipo_recurso": "PARAMEDICO", "alcanza": False}]}
    responses.add(responses.POST, f"{BASE}/validaciones", json=resultado)
    items = [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 5}]

    assert NacionalClient(BASE).validar("ALTO", items) == resultado
    assert json.loads(responses.calls[0].request.body) == {"gravedad": "ALTO", "items": items}


@responses.activate
def test_validar_con_422_o_caida_sale_como_nacional_error():
    responses.add(responses.POST, f"{BASE}/validaciones", status=422, json={"detail": "Tipo de recurso inexistente: X"})
    with pytest.raises(NacionalError):
        NacionalClient(BASE).validar("ALTO", [])


@responses.activate
def test_adjudicar_recursos_manda_el_payload():
    resultado = {"id": 4, "referencia_id": "emergencia-12"}
    responses.add(responses.POST, f"{BASE}/adjudicaciones", json=resultado, status=201)
    datos = {
        "referencia_id": "emergencia-12",
        "ong_id": 1,
        "emergencia_id": 12,
        "items": [{"inventario_id": 3, "cantidad": 2}],
    }

    assert NacionalClient(BASE).adjudicar_recursos_nacional(datos) == resultado
