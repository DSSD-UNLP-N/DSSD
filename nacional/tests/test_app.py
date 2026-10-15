def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok"}


def test_swagger_expone_el_titulo(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Sistema Nacional de Gestión de Recursos y Riesgos"
