from sqlalchemy import select

from app.models import Inventario, TipoRecurso

CRUZ_ROJA = "/ongs/30-54666544-5/inventario"


def _inv(client, cuit="30-54666544-5"):
    return {i["tipo_recurso"]: i for i in client.get(f"/ongs/{cuit}").json()["inventario"]}


def test_actualiza_la_cantidad_de_un_tipo_existente(client):
    r = client.put(CRUZ_ROJA, json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 9}]})
    assert r.status_code == 200
    por_tipo = {i["tipo_recurso"]: i for i in r.json()}
    assert por_tipo["PARAMEDICO"]["cantidad_total"] == 9
    assert por_tipo["PARAMEDICO"]["disponible"] == 9
    assert por_tipo["RACION_ALIMENTO"]["cantidad_total"] == 5000  # lo no enviado no se toca
    assert _inv(client)["PARAMEDICO"]["cantidad_total"] == 9


def test_agrega_un_tipo_nuevo_para_la_ong(client):
    assert "BOTE_RESCATE" not in _inv(client)
    r = client.put(CRUZ_ROJA, json={"items": [{"tipo_recurso": "BOTE_RESCATE", "cantidad_total": 2}]})
    assert r.status_code == 200
    bote = _inv(client)["BOTE_RESCATE"]
    assert (bote["cantidad_total"], bote["cantidad_comprometida"]) == (2, 0)
    assert bote["riesgo_permitido"] is None  # Cruz Roja no tiene RESCATE_ACUATICO


def test_declarar_cero_es_valido(client):
    r = client.put(CRUZ_ROJA, json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 0}]})
    assert r.status_code == 200
    assert _inv(client)["PARAMEDICO"]["disponible"] == 0


def test_no_se_puede_declarar_menos_de_lo_comprometido(client, session_factory):
    with session_factory() as db:
        tipo = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == "PARAMEDICO"))
        fila = db.scalars(select(Inventario).where(Inventario.tipo_recurso_id == tipo.id)).first()
        fila.cantidad_comprometida = 3
        db.commit()
        cuit_ong = fila.ong.cuit
    r = client.put(f"/ongs/{cuit_ong}/inventario", json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 2}]})
    assert r.status_code == 409
    assert "3 comprometidos" in r.json()["detail"]
    assert _inv(client, cuit_ong)["PARAMEDICO"]["cantidad_comprometida"] == 3
    ok = client.put(f"/ongs/{cuit_ong}/inventario", json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 3}]})
    assert ok.status_code == 200


def test_si_un_item_falla_no_se_guarda_ninguno(client):
    r = client.put(
        CRUZ_ROJA,
        json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 9}, {"tipo_recurso": "NADA", "cantidad_total": 1}]},
    )
    assert r.status_code == 404
    assert _inv(client)["PARAMEDICO"]["cantidad_total"] == 4


def test_ong_inexistente_da_404(client):
    r = client.put("/ongs/00-0-0/inventario", json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]})
    assert r.status_code == 404


def test_entradas_invalidas_dan_422(client):
    for body in (
        {"items": []},
        {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": -1}]},
        {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}, {"tipo_recurso": "PARAMEDICO", "cantidad_total": 2}]},
    ):
        assert client.put(CRUZ_ROJA, json=body).status_code == 422
