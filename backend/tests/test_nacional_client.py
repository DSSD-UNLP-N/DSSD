"""Cliente HTTP de la API Nacional, con HTTP simulado (`responses`)."""
import json

import pytest
import requests
import responses

from app.integrations.nacional import NacionalClient, NacionalError

BASE = "http://nacional.test"
TIPO = {"codigo": "PARAMEDICO", "nombre": "Paramédico", "categoria": "PERSONAL", "unidad": "personas",
        "certificacion_requerida": "SALUD_PREHOSP"}


@responses.activate
def test_tipos_recurso_devuelve_el_catalogo():
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[TIPO])
    assert NacionalClient(BASE).tipos_recurso() == [TIPO]


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


# --- JWT: la app entra con su cuenta de servicio -------------------------------------------------------------------

def _login(token="t1", **extra):
    responses.add(responses.POST, f"{BASE}/login", json={"access_token": token, "token_type": "bearer", **extra})


def _cliente():
    return NacionalClient(BASE, username="app-service", password="clave")


def _auth(i):
    return responses.calls[i].request.headers.get("Authorization")


@responses.activate
def test_sin_usuario_no_inicia_sesion_ni_manda_token():
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[])
    NacionalClient(BASE).tipos_recurso()
    assert [c.request.url for c in responses.calls] == [f"{BASE}/tipos-recurso"]
    assert _auth(0) is None


@responses.activate
def test_inicia_sesion_con_la_cuenta_de_servicio_y_manda_el_token():
    _login("t1")
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[TIPO])
    assert _cliente().tipos_recurso() == [TIPO]
    assert responses.calls[0].request.url == f"{BASE}/login"
    assert json.loads(responses.calls[0].request.body) == {"username": "app-service", "password": "clave"}
    assert _auth(1) == "Bearer t1"


@responses.activate
def test_el_login_se_hace_una_vez_por_proceso_aunque_el_cliente_sea_nuevo_cada_vez():
    _login("t1")
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[])
    _cliente().tipos_recurso()
    _cliente().tipos_recurso()
    assert [c.request.url for c in responses.calls].count(f"{BASE}/login") == 1
    assert _auth(2) == "Bearer t1"


@responses.activate
def test_si_nacional_contesta_401_vuelve_a_entrar_una_vez_y_reintenta():
    _login("viejo")
    _login("nuevo")  # el segundo login (Nacional sirve las respuestas en el orden en que se registran)
    responses.add(responses.GET, f"{BASE}/tipos-recurso", status=401)
    responses.add(responses.GET, f"{BASE}/tipos-recurso", json=[TIPO])
    assert _cliente().tipos_recurso() == [TIPO]
    assert [c.request.url.removeprefix(BASE) for c in responses.calls] == ["/login", "/tipos-recurso", "/login", "/tipos-recurso"]
    assert (_auth(1), _auth(3)) == ("Bearer viejo", "Bearer nuevo")


@responses.activate
def test_dos_401_seguidos_no_entran_en_bucle():
    _login("t1")
    responses.add(responses.GET, f"{BASE}/tipos-recurso", status=401)
    with pytest.raises(NacionalError):
        _cliente().tipos_recurso()
    assert len(responses.calls) == 4  # login, pedido, login, pedido: corta en el segundo 401


@responses.activate
@pytest.mark.parametrize("falla", [{"status": 401}, {"status": 500}, {"body": requests.ConnectionError("sin red")},
                                   {"json": {"sin_token": True}}])
def test_si_el_login_falla_sale_como_nacional_error(falla):
    responses.add(responses.POST, f"{BASE}/login", **falla)
    with pytest.raises(NacionalError, match="iniciar sesión"):
        _cliente().tipos_recurso()


@responses.activate
def test_get_nacional_usa_la_cuenta_de_servicio_de_la_configuracion():
    from app.core.config import get_settings
    from app.integrations.nacional import get_nacional

    s = get_settings()
    c = get_nacional(s)
    assert (c.username, c.password) == (s.nacional_service_username, s.nacional_service_password)
