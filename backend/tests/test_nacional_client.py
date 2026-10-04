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
