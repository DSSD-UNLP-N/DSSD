from sqlalchemy import select

from app.models import Inventario, Ong, TipoRecurso

CUIT = "30-54666544-5"


def _bloquear(session_factory, tipo: str, cantidad: int, cuit: str = CUIT) -> None:
    with session_factory() as db:
        ong = db.scalar(select(Ong).where(Ong.cuit == cuit))
        tipo_row = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == tipo))
        fila = db.scalar(
            select(Inventario).where(
                Inventario.ong_id == ong.id, Inventario.tipo_recurso_id == tipo_row.id
            )
        )
        fila.cantidad_comprometida = cantidad
        db.commit()


def _inv(client, tipo: str, cuit: str = CUIT) -> dict:
    inventario = client.get(f"/ongs/{cuit}").json()["inventario"]
    return next(i for i in inventario if i["tipo_recurso"] == tipo)


def test_liberar_baja_lo_comprometido_y_deja_constancia(client, session_factory):
    _bloquear(session_factory, "PARAMEDICO", 3)
    r = client.post(
        "/cierres",
        json={"cuit": CUIT, "referencia": "emergencia-12", "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 2}]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["referencia"] == "emergencia-12"
    assert body["ong"] == "Cruz Roja Argentina"
    item = body["items"][0]
    assert item["cantidad_liberada"] == 2
    assert (item["cantidad_total"], item["cantidad_comprometida"], item["disponible"]) == (4, 1, 3)
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 1

    guardado = client.get(f"/cierres/{body['id']}")
    assert guardado.status_code == 200
    assert guardado.json()["items"][0]["cantidad_liberada"] == 2


def test_libera_varios_tipos_en_un_solo_cierre(client, session_factory):
    _bloquear(session_factory, "PARAMEDICO", 2)
    _bloquear(session_factory, "AMBULANCIA", 1)
    r = client.post(
        "/cierres",
        json={
            "cuit": CUIT,
            "referencia": "emergencia-7",
            "items": [
                {"tipo_recurso": "PARAMEDICO", "cantidad": 2},
                {"tipo_recurso": "AMBULANCIA", "cantidad": 1},
            ],
        },
    )
    assert r.status_code == 201
    assert {i["tipo_recurso"]: i["cantidad_comprometida"] for i in r.json()["items"]} == {
        "PARAMEDICO": 0,
        "AMBULANCIA": 0,
    }


def test_si_un_item_no_alcanza_no_libera_ninguno(client, session_factory):
    _bloquear(session_factory, "PARAMEDICO", 3)
    _bloquear(session_factory, "AMBULANCIA", 1)
    r = client.post(
        "/cierres",
        json={
            "cuit": CUIT,
            "referencia": "emergencia-9",
            "items": [
                {"tipo_recurso": "PARAMEDICO", "cantidad": 4},
                {"tipo_recurso": "AMBULANCIA", "cantidad": 1},
            ],
        },
    )
    assert r.status_code == 409
    assert "PARAMEDICO" in r.json()["detail"]
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 3
    assert _inv(client, "AMBULANCIA")["cantidad_comprometida"] == 1
    assert client.get("/ongs/" + CUIT + "/cierres").json() == []


def test_la_misma_referencia_no_libera_dos_veces(client, session_factory):
    _bloquear(session_factory, "PARAMEDICO", 3)
    body = {"cuit": CUIT, "referencia": "emergencia-12", "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 1}]}
    assert client.post("/cierres", json=body).status_code == 201
    otra = client.post("/cierres", json=body)
    assert otra.status_code == 409
    assert "ya fue informado" in otra.json()["detail"]
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 2

    resto = client.post(
        "/cierres",
        json={"cuit": CUIT, "referencia": "emergencia-12-resto", "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 2}]},
    )
    assert resto.status_code == 201
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 0


def test_sin_bloqueados_da_409(client):
    r = client.post(
        "/cierres",
        json={"cuit": CUIT, "referencia": "emergencia-1", "items": [{"tipo_recurso": "BOTE_RESCATE", "cantidad": 1}]},
    )
    assert r.status_code == 409
    assert "0 bloqueados" in r.json()["detail"]


def test_ong_o_cierre_inexistente_da_404(client):
    r = client.post(
        "/cierres",
        json={"cuit": "00-0-0", "referencia": "x", "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 1}]},
    )
    assert r.status_code == 404
    assert client.get("/cierres/999").status_code == 404
    assert client.get("/ongs/00-0-0/cierres").status_code == 404


def test_tipo_inexistente_da_404(client):
    r = client.post(
        "/cierres",
        json={"cuit": CUIT, "referencia": "x", "items": [{"tipo_recurso": "NADA", "cantidad": 1}]},
    )
    assert r.status_code == 404


def test_entradas_invalidas_dan_422(client):
    for body in (
        {"cuit": CUIT, "referencia": "x", "items": []},
        {"cuit": CUIT, "referencia": "", "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 1}]},
        {"cuit": CUIT, "referencia": "x", "items": [{"tipo_recurso": "PARAMEDICO", "cantidad": 0}]},
        {
            "cuit": CUIT,
            "referencia": "x",
            "items": [
                {"tipo_recurso": "PARAMEDICO", "cantidad": 1},
                {"tipo_recurso": "PARAMEDICO", "cantidad": 1},
            ],
        },
    ):
        assert client.post("/cierres", json=body).status_code == 422
