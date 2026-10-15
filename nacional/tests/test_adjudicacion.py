from sqlalchemy import select

from app.models import Adjudicacion, Inventario

CUIT = "30-54666544-5"


def _inventario_id(session_factory) -> int:
    with session_factory() as db:
        return db.scalar(select(Inventario.id).where(Inventario.ong_id == 1))


def _body(inventario_id: int, referencia: str, cantidad: int) -> dict:
    return {
        "referencia_id": referencia,
        "ong_id": 1,
        "emergencia_id": 12,
        "items": [{"inventario_id": inventario_id, "cantidad": cantidad}],
    }


def test_adjudicar_incrementa_comprometido_y_es_idempotente(client, session_factory):
    inventario_id = _inventario_id(session_factory)
    body = _body(inventario_id, "emergencia-12", 2)

    creada = client.post("/adjudicaciones", json=body)
    repetida = client.post("/adjudicaciones", json=body)

    assert creada.status_code == 201
    assert repetida.status_code == 200
    assert repetida.json()["id"] == creada.json()["id"]

    with session_factory() as db:
        fila = db.get(Inventario, inventario_id)
        assert fila.cantidad_comprometida == 2
        assert db.scalar(select(Adjudicacion.referencia_id)) == "emergencia-12"


def test_adjudicar_rechaza_stock_sin_modificarlo(client, session_factory):
    inventario_id = _inventario_id(session_factory)
    response = client.post("/adjudicaciones", json=_body(inventario_id, "sin-stock", 5))

    assert response.status_code == 409
    with session_factory() as db:
        assert db.get(Inventario, inventario_id).cantidad_comprometida == 0
