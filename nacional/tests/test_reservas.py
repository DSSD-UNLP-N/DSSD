"""Evaluación con reserva, confirmación y liberación (SQLite; la concurrencia real va en test_concurrencia_reservas.py)."""
from sqlalchemy import select

from app.models import Adjudicacion, EstadoAdjudicacion, Inventario, Ong, TipoRecurso

CRUZ_ROJA = "30-54666544-5"  # 4 paramédicos (certificación hasta riesgo MEDIO), 3000 L de agua, 5000 raciones
BOMBEROS = "30-68522415-9"   # 6 paramédicos con la certificación vencida
SUSPENDIDA = "30-70000000-1"


def _cuerpo(*ofertas, lotes=None, gravedad="ALTO", ronda=1, emergencia_id=12):
    """ofertas: (cuit, [(lote_id, tipo_recurso, cantidad), ...])."""
    return {
        "emergencia_id": emergencia_id, "ronda": ronda, "gravedad": gravedad,
        "lotes": lotes if lotes is not None else [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 10}],
        "ofertas": [{"cuit": c, "items": [{"lote_id": l, "tipo_recurso": t, "cantidad": n} for l, t, n in items]}
                    for c, items in ofertas],
    }


def _comprometido(session_factory, cuit, tipo):
    with session_factory() as db:
        return db.scalar(
            select(Inventario.cantidad_comprometida)
            .join(Ong).join(TipoRecurso).where(Ong.cuit == cuit, TipoRecurso.codigo == tipo)
        )


def _estado(session_factory, referencia):
    with session_factory() as db:
        return db.scalar(select(Adjudicacion.estado).where(Adjudicacion.referencia_id == referencia))


def test_evaluar_reserva_lo_ofrecido_y_calcula_la_cobertura(client, session_factory):
    r = client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)]), (BOMBEROS, [(1, "PARAMEDICO", 2)])))

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["lotes"] == [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "pedido": 10, "reservado": 6,
                                "porcentaje": 60.0, "cubierto": False}]
    assert cuerpo["cobertura_completa"] is False and cuerpo["porcentaje_cobertura"] == 60.0
    assert [(o["cuit"], o["referencia"], o["estado"]) for o in cuerpo["ongs"]] == [
        (CRUZ_ROJA, "emg-12-r1-30-54666544-5", "RESERVADA"), (BOMBEROS, "emg-12-r1-30-68522415-9", "RESERVADA")]
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 4
    assert _comprometido(session_factory, BOMBEROS, "PARAMEDICO") == 2


def test_cada_item_trae_su_nivel_de_competencia(client):
    ongs = client.post("/evaluaciones", json=_cuerpo(
        (CRUZ_ROJA, [(1, "PARAMEDICO", 4)]), (BOMBEROS, [(1, "PARAMEDICO", 2)]))).json()["ongs"]

    cruz, bomberos = (o["items"][0] for o in ongs)
    assert (cruz["nivel"], cruz["riesgo_permitido"], cruz["asignacion_sugerida"]) == ("PARCIAL", "MEDIO", "APOYO")
    assert cruz["ofrecido"] == 4 and cruz["reservado"] == 4
    assert "SALUD_PREHOSP vigente hasta riesgo MEDIO; la emergencia es ALTO" in cruz["observaciones"]
    assert (bomberos["nivel"], bomberos["riesgo_permitido"]) == ("SUPERVISADA", None)


def test_repetir_la_evaluacion_devuelve_lo_mismo_y_no_reserva_dos_veces(client, session_factory):
    cuerpo = _cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)]))
    primera = client.post("/evaluaciones", json=cuerpo)
    segunda = client.post("/evaluaciones", json=cuerpo)

    assert segunda.status_code == 200 and segunda.json() == primera.json()
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 4
    with session_factory() as db:
        assert len(db.scalars(select(Adjudicacion)).all()) == 1


def test_lo_ofrecido_en_varios_lotes_se_suma_por_recurso(client, session_factory):
    lotes = [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 3},
             {"lote_id": 2, "tipo_recurso": "PARAMEDICO", "cantidad": 3}]
    r = client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 2), (2, "PARAMEDICO", 2)]), lotes=lotes))

    items = r.json()["ongs"][0]["items"]
    assert [(i["lote_id"], i["ofrecido"], i["reservado"]) for i in items] == [(1, 2, 2), (2, 2, 2)]
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 4  # 2 + 2 = todo lo que tiene


def test_si_no_alcanza_no_se_reserva_nada_ni_se_recorta_la_oferta(client, session_factory):
    lotes = [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 3},
             {"lote_id": 2, "tipo_recurso": "PARAMEDICO", "cantidad": 3}]
    r = client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 3), (2, "PARAMEDICO", 3)]), lotes=lotes))

    ong = r.json()["ongs"][0]
    assert (ong["estado"], ong["referencia"]) == ("NO_RESERVADA", None)
    assert [(i["lote_id"], i["ofrecido"], i["reservado"]) for i in ong["items"]] == [(1, 3, 0), (2, 3, 0)]
    assert "Oferta sin reservar: Paramédico: ofrecida 6 y disponible 4" in ong["items"][0]["observaciones"]
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 0
    assert [l["reservado"] for l in r.json()["lotes"]] == [0, 0]
    with session_factory() as db:
        assert db.scalars(select(Adjudicacion)).all() == []


def test_todo_o_nada_tambien_entre_recursos_de_la_misma_oferta(client, session_factory):
    lotes = [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 4},
             {"lote_id": 2, "tipo_recurso": "AGUA_POTABLE", "cantidad": 5000}]
    r = client.post("/evaluaciones", json=_cuerpo(
        (CRUZ_ROJA, [(1, "PARAMEDICO", 4), (2, "AGUA_POTABLE", 3001)]), lotes=lotes))

    assert r.json()["ongs"][0]["estado"] == "NO_RESERVADA"
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 0  # los paramédicos entraban, pero la oferta es una
    assert _comprometido(session_factory, CRUZ_ROJA, "AGUA_POTABLE") == 0


def test_lo_que_sobra_del_lote_se_reserva_entero(client, session_factory):
    lotes = [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 3}]
    r = client.post("/evaluaciones", json=_cuerpo(
        (CRUZ_ROJA, [(1, "PARAMEDICO", 4)]), (BOMBEROS, [(1, "PARAMEDICO", 2)]), lotes=lotes))

    assert [l["reservado"] for l in r.json()["lotes"]] == [6]
    assert (r.json()["lotes"][0]["porcentaje"], r.json()["cobertura_completa"]) == (100.0, True)
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 4  # nada se descarta: elige el Municipio


def test_la_cobertura_es_el_promedio_simple_de_los_lotes(client):
    lotes = [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 10},
             {"lote_id": 2, "tipo_recurso": "AGUA_POTABLE", "cantidad": 5000},
             {"lote_id": 3, "tipo_recurso": "RACION_ALIMENTO", "cantidad": 100}]
    r = client.post("/evaluaciones", json=_cuerpo(
        (CRUZ_ROJA, [(1, "PARAMEDICO", 4), (2, "AGUA_POTABLE", 3000), (3, "RACION_ALIMENTO", 100)]),
        (BOMBEROS, [(1, "PARAMEDICO", 2)]), lotes=lotes))

    cuerpo = r.json()
    assert [l["porcentaje"] for l in cuerpo["lotes"]] == [60.0, 60.0, 100.0]
    assert [l["cubierto"] for l in cuerpo["lotes"]] == [False, False, True]
    assert cuerpo["porcentaje_cobertura"] == 73.3 and cuerpo["cobertura_completa"] is False


def test_cobertura_completa_cuando_todos_los_lotes_alcanzan(client):
    r = client.post("/evaluaciones", json=_cuerpo(
        (CRUZ_ROJA, [(1, "PARAMEDICO", 4)]), (BOMBEROS, [(1, "PARAMEDICO", 6)])))

    assert r.json()["cobertura_completa"] is True and r.json()["porcentaje_cobertura"] == 100.0


def test_sin_ofertas_la_cobertura_es_cero(client):
    r = client.post("/evaluaciones", json=_cuerpo())

    assert r.status_code == 200
    assert r.json()["ongs"] == [] and r.json()["cobertura_completa"] is False
    assert r.json()["porcentaje_cobertura"] == 0.0 and r.json()["lotes"][0]["reservado"] == 0


def test_la_reserva_baja_el_disponible_que_ven_las_validaciones(client):
    client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)])))

    r = client.post("/validaciones", json={"gravedad": "ALTO", "items": [
        {"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 1}]})

    resultado = r.json()["resultados"][0]
    assert resultado["disponible"] == 0 and resultado["alcanza"] is False


def test_una_ong_no_registrada_no_reserva_nada(client):
    r = client.post("/evaluaciones", json=_cuerpo(("30-99999999-9", [(1, "PARAMEDICO", 2)])))

    ong = r.json()["ongs"][0]
    assert (ong["estado"], ong["referencia"], ong["items"][0]["reservado"]) == ("NO_RESERVADA", None, 0)
    assert "Oferta sin reservar: ONG no registrada en el Sistema Nacional" in ong["items"][0]["observaciones"]


def test_una_ong_suspendida_no_reserva_nada(client, session_factory):
    r = client.post("/evaluaciones", json=_cuerpo(
        (SUSPENDIDA, [(1, "RACION_ALIMENTO", 100)]), lotes=[{"lote_id": 1, "tipo_recurso": "RACION_ALIMENTO", "cantidad": 100}]))

    ong = r.json()["ongs"][0]
    assert (ong["estado"], ong["referencia"], ong["items"][0]["reservado"]) == ("NO_RESERVADA", None, 0)
    assert "ONG suspendida: no está habilitada para comprometer recursos" in ong["items"][0]["observaciones"]
    assert _comprometido(session_factory, SUSPENDIDA, "RACION_ALIMENTO") == 0


def test_pedidos_invalidos(client):
    assert client.post("/evaluaciones", json=_cuerpo(
        (CRUZ_ROJA, [(1, "PARAMEDICO", 1)]), (CRUZ_ROJA, [(1, "PARAMEDICO", 1)]))).status_code == 400
    assert client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 1), (1, "PARAMEDICO", 1)]))).status_code == 400
    assert client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "NAVE_ESPACIAL", 1)]))).status_code == 422
    assert client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 0)]))).status_code == 422


def test_confirmar_pasa_a_adjudicada_sin_tocar_el_stock_y_es_idempotente(client, session_factory):
    ref = "emg-12-r1-" + CRUZ_ROJA
    client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)])))

    primera = client.post(f"/adjudicaciones/{ref}/confirmar")
    segunda = client.post(f"/adjudicaciones/{ref}/confirmar")

    assert primera.status_code == segunda.status_code == 200
    assert primera.json() == {"referencia": ref, "estado": "ADJUDICADA"}
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 4
    assert _estado(session_factory, ref) is EstadoAdjudicacion.ADJUDICADA


def test_liberar_devuelve_el_stock_y_repetirlo_no_resta_dos_veces(client, session_factory):
    ref = "emg-12-r1-" + CRUZ_ROJA
    client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)]), (BOMBEROS, [(1, "PARAMEDICO", 2)])))

    primera = client.post(f"/adjudicaciones/{ref}/liberar")
    segunda = client.post(f"/adjudicaciones/{ref}/liberar")

    assert primera.status_code == segunda.status_code == 200
    assert primera.json() == {"referencia": ref, "estado": "LIBERADA",
                              "liberado": [{"tipo_recurso": "PARAMEDICO", "cantidad": 4}]}
    assert segunda.json() == primera.json()
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 0
    assert _comprometido(session_factory, BOMBEROS, "PARAMEDICO") == 2  # la otra reserva no se toca


def test_liberar_una_adjudicada_tambien_devuelve_el_stock(client, session_factory):
    ref = "emg-12-r1-" + CRUZ_ROJA
    client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)])))
    client.post(f"/adjudicaciones/{ref}/confirmar")

    assert client.post(f"/adjudicaciones/{ref}/liberar").status_code == 200
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 0


def test_una_liberada_no_se_confirma_ni_se_evalua_de_nuevo(client, session_factory):
    ref = "emg-12-r1-" + CRUZ_ROJA
    cuerpo = _cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)]))
    client.post("/evaluaciones", json=cuerpo)
    client.post(f"/adjudicaciones/{ref}/liberar")

    assert client.post(f"/adjudicaciones/{ref}/confirmar").status_code == 409
    assert client.post("/evaluaciones", json=cuerpo).status_code == 409
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 0


def test_una_ronda_nueva_reserva_de_nuevo_con_otra_referencia(client, session_factory):
    client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)])))
    client.post("/adjudicaciones/emg-12-r1-" + CRUZ_ROJA + "/liberar")

    r = client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 3)]), ronda=2))

    assert r.json()["ongs"][0]["referencia"] == "emg-12-r2-" + CRUZ_ROJA
    assert _comprometido(session_factory, CRUZ_ROJA, "PARAMEDICO") == 3


def test_confirmar_o_liberar_una_referencia_inexistente_da_404(client):
    assert client.post("/adjudicaciones/no-existe/confirmar").status_code == 404
    assert client.post("/adjudicaciones/no-existe/liberar").status_code == 404


def test_una_cerrada_no_se_libera_ni_se_confirma(client, session_factory):
    ref = "emg-12-r1-" + CRUZ_ROJA
    client.post("/evaluaciones", json=_cuerpo((CRUZ_ROJA, [(1, "PARAMEDICO", 4)])))
    with session_factory() as db:
        db.scalar(select(Adjudicacion)).estado = EstadoAdjudicacion.CERRADA
        db.commit()

    assert client.post(f"/adjudicaciones/{ref}/liberar").status_code == 409
    assert client.post(f"/adjudicaciones/{ref}/confirmar").status_code == 409
