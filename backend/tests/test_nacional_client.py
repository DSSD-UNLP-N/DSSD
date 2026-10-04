"""Cliente HTTP de la API Nacional, con HTTP simulado (`responses`)."""
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
