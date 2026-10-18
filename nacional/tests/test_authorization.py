from app.config import get_settings


def _headers(client, username, password="demo1234"):
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_catalogo_requiere_token_y_acepta_cualquier_rol(client):
    assert client.get("/tipos-recurso", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/tipos-recurso", headers=_headers(client, "auditor")).status_code == 200


def test_inventario_solo_permite_a_la_ong_propia(client, ong_headers):
    body = {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 4}]}
    propia = client.put(
        "/ongs/30-54666544-5/inventario",
        json=body,
        headers=ong_headers("30-54666544-5"),
    )
    ajena = client.put(
        "/ongs/30-68522415-9/inventario",
        json=body,
        headers=ong_headers("30-54666544-5"),
    )
    municipal = client.put(
        "/ongs/30-54666544-5/inventario",
        json=body,
        headers=_headers(client, "operador.municipal"),
    )

    assert propia.status_code == 200
    assert ajena.status_code == 403
    assert municipal.status_code == 403


def test_validacion_acepta_token_de_usuario_y_evaluacion_exige_bonita(client):
    municipal = _headers(client, "operador.municipal")
    body = {
        "emergencia_id": 99,
        "ronda": 1,
        "gravedad": "BAJO",
        "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 1}],
        "ofertas": [],
    }

    assert client.post(
        "/validaciones",
        json={
            "gravedad": "BAJO",
            "items": [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 1}],
        },
        headers=municipal,
    ).status_code == 200
    assert client.post("/evaluaciones", json=body, headers=municipal).status_code == 403

    settings = get_settings()
    bonita = _headers(
        client,
        settings.bonita_service_username,
        settings.bonita_service_password,
    )
    assert client.post("/evaluaciones", json=body, headers=bonita).status_code == 200


def test_adjudicacion_y_cierre_exigen_cuenta_de_servicio_bonita(client, ong_headers):
    ong = ong_headers("30-54666544-5")
    municipal = _headers(client, "operador.municipal")
    settings = get_settings()
    bonita = _headers(
        client,
        settings.bonita_service_username,
        settings.bonita_service_password,
    )

    assert client.post(
        "/adjudicaciones/no-existe/confirmar",
        headers=municipal,
    ).status_code == 403
    assert client.post(
        "/adjudicaciones/no-existe/confirmar",
        headers=bonita,
    ).status_code == 404
    cierre = {
        "cuit": "30-54666544-5",
        "referencia": "no-existe",
        "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 1}],
    }
    assert client.post("/cierres", json=cierre, headers=ong).status_code == 403
    assert client.post("/cierres", json=cierre, headers=bonita).status_code == 409
