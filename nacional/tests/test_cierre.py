"""Cierre de una adjudicación: libera exactamente lo que esa referencia tenía comprometido."""
from sqlalchemy import select

from app.models import Adjudicacion, EstadoAdjudicacion

CRUZ_ROJA = "30-54666544-5"  # 4 paramédicos
BOMBEROS = "30-68522415-9"   # 6 paramédicos


def _ref(emergencia: int, cuit: str = CRUZ_ROJA, ronda: int = 1) -> str:
    return f"emg-{emergencia}-r{ronda}-{cuit}"


def _evaluar(client, emergencia: int, *ofertas):
    """ofertas: (cuit, cantidad de paramédicos). Devuelve la respuesta de /evaluaciones."""
    return client.post("/evaluaciones", json={
        "emergencia_id": emergencia, "ronda": 1, "gravedad": "ALTO",
        "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 10}],
        "ofertas": [{"cuit": c, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": n}]}
                    for c, n in ofertas],
    })


def _adjudicar(client, emergencia: int, *ofertas):
    assert _evaluar(client, emergencia, *ofertas).status_code == 200
    for cuit, _ in ofertas:
        assert client.post(f"/adjudicaciones/{_ref(emergencia, cuit)}/confirmar").status_code == 200


def _inv(client, tipo: str = "PARAMEDICO", cuit: str = CRUZ_ROJA) -> dict:
    return next(i for i in client.get(f"/ongs/{cuit}").json()["inventario"] if i["tipo_recurso"] == tipo)


def _sin_hora(cierre: dict) -> dict:
    """SQLite devuelve la hora sin zona y la respuesta recién creada la trae con Z; en Postgres coinciden."""
    return {k: v for k, v in cierre.items() if k != "informado_en"}


def _cerrar(client, ref: str, cuit: str = CRUZ_ROJA):
    return client.post("/cierres", json={"cuit": cuit, "referencia": ref})


def test_cerrar_devuelve_lo_comprometido_y_deja_constancia(client, session_factory):
    _adjudicar(client, 12, (CRUZ_ROJA, 4))
    assert _inv(client)["cantidad_comprometida"] == 4

    r = _cerrar(client, _ref(12))

    assert r.status_code == 201
    body = r.json()
    assert (body["cuit"], body["ong"], body["referencia"]) == (CRUZ_ROJA, "Cruz Roja Argentina", _ref(12))
    item = body["items"][0]
    assert item["tipo_recurso"] == "PARAMEDICO" and item["cantidad_liberada"] == 4
    assert (item["cantidad_total"], item["cantidad_comprometida"], item["disponible"]) == (4, 0, 4)
    assert _inv(client)["cantidad_comprometida"] == 0
    assert _sin_hora(client.get(f"/cierres/{body['id']}").json()) == _sin_hora(body)
    assert [_sin_hora(c) for c in client.get(f"/ongs/{CRUZ_ROJA}/cierres").json()] == [_sin_hora(body)]
    with session_factory() as db:
        assert db.scalar(select(Adjudicacion.estado)) is EstadoAdjudicacion.CERRADA


def test_reservar_confirmar_y_cerrar_deja_el_inventario_como_al_principio(client):
    antes = client.get(f"/ongs/{CRUZ_ROJA}").json()["inventario"]

    _adjudicar(client, 12, (CRUZ_ROJA, 4))
    assert client.get(f"/ongs/{CRUZ_ROJA}").json()["inventario"] != antes
    _cerrar(client, _ref(12))

    assert client.get(f"/ongs/{CRUZ_ROJA}").json()["inventario"] == antes


def test_cerrar_una_referencia_no_toca_lo_de_otra_de_la_misma_ong(client):
    _adjudicar(client, 12, (CRUZ_ROJA, 1))
    _adjudicar(client, 13, (CRUZ_ROJA, 3))
    assert _inv(client)["cantidad_comprometida"] == 4

    r = _cerrar(client, _ref(12))

    assert r.json()["items"][0]["cantidad_liberada"] == 1
    assert _inv(client)["cantidad_comprometida"] == 3  # la emergencia 13 sigue bloqueada


def test_repetir_el_cierre_devuelve_el_mismo_sin_restar_de_nuevo(client):
    _adjudicar(client, 12, (CRUZ_ROJA, 1))
    _adjudicar(client, 13, (CRUZ_ROJA, 3))
    primero = _cerrar(client, _ref(12))
    segundo = _cerrar(client, _ref(12))

    assert (primero.status_code, segundo.status_code) == (201, 200)
    assert _sin_hora(segundo.json()) == _sin_hora(primero.json())
    assert _inv(client)["cantidad_comprometida"] == 3
    assert len(client.get(f"/ongs/{CRUZ_ROJA}/cierres").json()) == 1


def test_una_reserva_sin_confirmar_no_se_puede_cerrar(client):
    _evaluar(client, 12, (CRUZ_ROJA, 4))

    r = _cerrar(client, _ref(12))

    assert r.status_code == 409 and "RESERVADA" in r.json()["detail"]
    assert _inv(client)["cantidad_comprometida"] == 4
    assert client.get(f"/ongs/{CRUZ_ROJA}/cierres").json() == []


def test_una_reserva_liberada_no_se_puede_cerrar(client):
    _adjudicar(client, 12, (CRUZ_ROJA, 4))
    assert client.post(f"/adjudicaciones/{_ref(12)}/liberar").status_code == 200

    r = _cerrar(client, _ref(12))

    assert r.status_code == 409 and "LIBERADA" in r.json()["detail"]
    assert _inv(client)["cantidad_comprometida"] == 0


def test_una_cerrada_no_se_vuelve_a_evaluar_ni_a_liberar_ni_a_confirmar(client):
    _adjudicar(client, 12, (CRUZ_ROJA, 4))
    _cerrar(client, _ref(12))

    assert _evaluar(client, 12, (CRUZ_ROJA, 4)).status_code == 409
    assert client.post(f"/adjudicaciones/{_ref(12)}/liberar").status_code == 409
    assert client.post(f"/adjudicaciones/{_ref(12)}/confirmar").status_code == 409
    assert _inv(client)["cantidad_comprometida"] == 0


def test_ong_o_referencia_inexistente_da_404(client):
    _adjudicar(client, 12, (CRUZ_ROJA, 2))

    assert _cerrar(client, _ref(12), cuit="00-0-0").status_code == 404
    assert _cerrar(client, "emg-99-r1-30-54666544-5").status_code == 404
    assert client.get("/cierres/999").status_code == 404
    assert client.get("/ongs/00-0-0/cierres").status_code == 404
    assert _inv(client)["cantidad_comprometida"] == 2


def test_no_se_puede_cerrar_la_referencia_de_otra_ong(client):
    _adjudicar(client, 12, (CRUZ_ROJA, 2))

    r = _cerrar(client, _ref(12), cuit=BOMBEROS)

    assert r.status_code == 404
    assert _inv(client)["cantidad_comprometida"] == 2


def test_entradas_invalidas_dan_422(client):
    for body in ({"cuit": CRUZ_ROJA}, {"referencia": "x"}, {"cuit": CRUZ_ROJA, "referencia": ""}, {"cuit": "", "referencia": "x"}):
        assert client.post("/cierres", json=body).status_code == 422
