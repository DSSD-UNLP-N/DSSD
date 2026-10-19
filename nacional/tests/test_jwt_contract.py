from app.config import get_settings


PROTECTED_OPERATIONS = {
    ("GET", "/tipos-recurso"),
    ("GET", "/certificaciones"),
    ("GET", "/ongs"),
    ("GET", "/ongs/{cuit}"),
    ("PUT", "/ongs/{cuit}/inventario"),
    ("GET", "/recursos/disponibilidad"),
    ("POST", "/validaciones"),
    ("POST", "/evaluaciones"),
    ("POST", "/adjudicaciones"),
    ("POST", "/adjudicaciones/{referencia}/confirmar"),
    ("POST", "/adjudicaciones/{referencia}/liberar"),
    ("POST", "/adjudicaciones/resolucion"),
    ("POST", "/cierres"),
    ("POST", "/cierres/lote"),
    ("GET", "/cierres/{cierre_id}"),
    ("GET", "/ongs/{cuit}/cierres"),
}


def _token_headers(client, username, password="demo1234"):
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_openapi_refleja_los_permisos_jwt_documentados(client):
    paths = client.get("/openapi.json").json()["paths"]

    for method, path in PROTECTED_OPERATIONS:
        security = paths[path][method.lower()]["security"]
        assert any("HTTPBearer" in requirement for requirement in security), (method, path)

    for path in ("/login", "/ongs"):
        assert "security" not in paths[path]["post"], path
    assert "security" not in paths["/health"]["get"]


def test_todos_los_endpoints_protegidos_rechazan_solicitudes_sin_token(client):
    client.headers.pop("Authorization", None)
    requests = [
        ("GET", "/tipos-recurso", None),
        ("GET", "/certificaciones", None),
        ("GET", "/ongs?estado=HABILITADA", None),
        ("GET", "/ongs/30-54666544-5", None),
        ("PUT", "/ongs/30-54666544-5/inventario", {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 4}]}),
        ("GET", "/recursos/disponibilidad?tipo_recurso=PARAMEDICO", None),
        ("POST", "/validaciones", {
            "gravedad": "BAJO",
            "items": [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 1}],
        }),
        ("POST", "/evaluaciones", {
            "emergencia_id": 99,
            "ronda": 1,
            "gravedad": "BAJO",
            "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 1}],
            "ofertas": [],
        }),
        ("POST", "/adjudicaciones", {
            "referencia_id": "sin-token",
            "ong_id": 1,
            "emergencia_id": 99,
            "items": [{"inventario_id": 1, "cantidad": 1}],
        }),
        ("POST", "/adjudicaciones/no-existe/confirmar", None),
        ("POST", "/adjudicaciones/no-existe/liberar", None),
        ("POST", "/adjudicaciones/resolucion", {"confirmar": [], "liberar": []}),
        ("POST", "/cierres", {
            "cuit": "30-54666544-5",
            "referencia": "sin-token",
            "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 1}],
        }),
        ("POST", "/cierres/lote", {"cierres": []}),
        ("GET", "/cierres/1", None),
        ("GET", "/ongs/30-54666544-5/cierres", None),
    ]

    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.status_code, response.text)


def test_rutas_de_lectura_aceptan_jwt_de_cualquier_rol(client):
    headers = _token_headers(client, "auditor")

    assert client.get("/tipos-recurso", headers=headers).status_code == 200
    assert client.get("/certificaciones", headers=headers).status_code == 200
    assert client.get("/ongs?estado=HABILITADA", headers=headers).status_code == 200
    assert client.get("/ongs/30-54666544-5", headers=headers).status_code == 200
    assert client.get("/recursos/disponibilidad?tipo_recurso=PARAMEDICO", headers=headers).status_code == 200
    assert client.post(
        "/validaciones",
        json={
            "gravedad": "BAJO",
            "items": [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 1}],
        },
        headers=headers,
    ).status_code == 200


def test_inventario_solo_se_actualiza_con_el_token_de_la_ong_propietaria(client):
    body = {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 4}]}
    propia = client.put(
        "/ongs/30-54666544-5/inventario",
        json=body,
        headers=_token_headers(client, "ong.cruzroja"),
    )
    ajena = client.put(
        "/ongs/30-68522415-9/inventario",
        json=body,
        headers=_token_headers(client, "ong.cruzroja"),
    )
    municipal = client.put(
        "/ongs/30-54666544-5/inventario",
        json=body,
        headers=_token_headers(client, "operador.municipal"),
    )

    assert propia.status_code == 200
    assert ajena.status_code == 403
    assert municipal.status_code == 403


def test_operaciones_reservadas_a_bonita_rechazan_otros_roles(client):
    headers = _token_headers(client, "operador.municipal")
    operaciones = [
        ("POST", "/evaluaciones", {
            "emergencia_id": 99,
            "ronda": 1,
            "gravedad": "BAJO",
            "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 1}],
            "ofertas": [],
        }),
        ("POST", "/adjudicaciones", {
            "referencia_id": "solo-bonita",
            "ong_id": 1,
            "emergencia_id": 99,
            "items": [{"inventario_id": 1, "cantidad": 1}],
        }),
        ("POST", "/adjudicaciones/no-existe/confirmar", None),
        ("POST", "/adjudicaciones/no-existe/liberar", None),
        ("POST", "/adjudicaciones/resolucion", {"confirmar": [], "liberar": []}),
        ("POST", "/cierres", {
            "cuit": "30-54666544-5",
            "referencia": "solo-bonita",
            "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 1}],
        }),
        ("POST", "/cierres/lote", {"cierres": []}),
        ("GET", "/cierres/1", None),
        ("GET", "/ongs/30-54666544-5/cierres", None),
    ]

    for method, path, body in operaciones:
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403, (method, path, response.status_code, response.text)


def test_solo_jwt_de_servicio_puede_listar_cierres(client, ong_headers):
    ong = ong_headers("30-54666544-5")
    settings = get_settings()
    bonita = _token_headers(
        client,
        settings.bonita_service_username,
        settings.bonita_service_password,
    )

    assert client.get("/ongs/30-54666544-5/cierres", headers=ong).status_code == 403
    assert client.get("/ongs/30-54666544-5/cierres", headers=bonita).status_code == 200
