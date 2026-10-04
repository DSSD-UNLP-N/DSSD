from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import Inventario, Ong, TipoRecurso
from app.schemas import ItemValidacionIn
from app.services.validacion import validar

CRUZ_ROJA = "30-54666544-5"  # SALUD_PREHOSP hasta MEDIO; 4 paramédicos
BOMBEROS = "30-68522415-9"  # RESCATE_ACUATICO CRITICO, INCENDIO_FORESTAL ALTO, SALUD_PREHOSP vencida
SUSPENDIDA = "30-70000000-1"


def _validar(client, gravedad, *items):
    r = client.post(
        "/validaciones",
        json={"gravedad": gravedad, "items": [{"cuit": c, "tipo_recurso": t, "cantidad": n} for c, t, n in items]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _unico(client, gravedad, cuit, tipo, cantidad):
    (resultado,) = _validar(client, gravedad, (cuit, tipo, cantidad))["resultados"]
    return resultado


def test_pedir_mas_de_lo_que_tiene_no_alcanza(client):
    r = _unico(client, "ALTO", CRUZ_ROJA, "PARAMEDICO", 10)
    assert (r["solicitado"], r["disponible"], r["alcanza"]) == (10, 4, False)
    assert "Solicitado 10, disponible 4" in r["observaciones"]


def test_el_resultado_trae_nombre_y_unidad_del_recurso(client):
    r = _unico(client, "MEDIO", CRUZ_ROJA, "PARAMEDICO", 1)
    assert (r["tipo_recurso"], r["nombre_recurso"], r["unidad"]) == ("PARAMEDICO", "Paramédico", "personas")


def test_pedir_justo_lo_que_tiene_alcanza(client):
    assert _unico(client, "MEDIO", CRUZ_ROJA, "PARAMEDICO", 4)["alcanza"] is True


def test_las_cantidades_del_mismo_recurso_se_suman(client):
    """2 y después 3 de un recurso con 4: entre las dos pasan el tope."""
    resp = _validar(client, "MEDIO", (CRUZ_ROJA, "PARAMEDICO", 2), (CRUZ_ROJA, "PARAMEDICO", 3))
    (r,) = resp["resultados"]
    assert (r["solicitado"], r["disponible"], r["alcanza"]) == (5, 4, False)
    assert resp["alcanza_todo"] is False


def test_lo_comprometido_no_esta_disponible(client, session_factory):
    with session_factory() as db:
        ong = db.scalar(select(Ong).where(Ong.cuit == CRUZ_ROJA))
        tipo = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == "PARAMEDICO"))
        fila = db.scalar(select(Inventario).where(Inventario.ong_id == ong.id, Inventario.tipo_recurso_id == tipo.id))
        fila.cantidad_comprometida = 3
        db.commit()
    r = _unico(client, "MEDIO", CRUZ_ROJA, "PARAMEDICO", 2)
    assert (r["disponible"], r["alcanza"]) == (1, False)


def test_certificacion_suficiente_es_plena_y_va_a_lote_principal(client):
    r = _unico(client, "MEDIO", CRUZ_ROJA, "PARAMEDICO", 2)  # riesgo_max MEDIO >= MEDIO
    assert (r["nivel"], r["riesgo_permitido"], r["asignacion_sugerida"]) == ("PLENA", "MEDIO", "PRINCIPAL")
    assert r["observaciones"] == []


def test_certificacion_de_menor_riesgo_es_parcial_y_va_a_apoyo(client):
    r = _unico(client, "ALTO", CRUZ_ROJA, "PARAMEDICO", 2)  # MEDIO < ALTO
    assert (r["nivel"], r["riesgo_permitido"], r["asignacion_sugerida"]) == ("PARCIAL", "MEDIO", "APOYO")
    assert r["alcanza"] is True  # la competencia no descarta la oferta
    assert "SALUD_PREHOSP vigente hasta riesgo MEDIO; la emergencia es ALTO" in r["observaciones"]


def test_el_riesgo_critico_solo_lo_cubre_una_certificacion_critica(client):
    assert _unico(client, "CRITICO", BOMBEROS, "RESCATISTA_ACUATICO", 5)["nivel"] == "PLENA"
    assert _unico(client, "CRITICO", BOMBEROS, "BRIGADISTA_FORESTAL", 5)["nivel"] == "PARCIAL"  # ALTO < CRITICO


def test_certificacion_vencida_deja_la_oferta_supervisada(client):
    r = _unico(client, "BAJO", BOMBEROS, "PARAMEDICO", 2)
    assert (r["nivel"], r["riesgo_permitido"], r["asignacion_sugerida"]) == ("SUPERVISADA", None, "APOYO")
    assert r["alcanza"] is True  # tiene los 6; el problema es la competencia, no la cantidad
    assert any("vencida el" in o for o in r["observaciones"])


def test_sin_la_certificacion_requerida_queda_supervisada(client):
    r = _unico(client, "BAJO", CRUZ_ROJA, "BOTE_RESCATE", 1)
    assert (r["nivel"], r["asignacion_sugerida"]) == ("SUPERVISADA", "APOYO")
    assert (r["disponible"], r["alcanza"]) == (0, False)  # tampoco tiene botes en inventario
    assert "Sin certificación RESCATE_ACUATICO" in r["observaciones"]


def test_los_insumos_no_requieren_certificacion(client):
    r = _unico(client, "CRITICO", CRUZ_ROJA, "RACION_ALIMENTO", 1000)
    assert (r["nivel"], r["riesgo_permitido"], r["asignacion_sugerida"]) == ("PLENA", "CRITICO", "PRINCIPAL")


def test_una_ong_suspendida_no_puede_comprometer_nada(client):
    r = _unico(client, "BAJO", SUSPENDIDA, "RACION_ALIMENTO", 10)
    assert (r["nivel"], r["disponible"], r["alcanza"]) == ("SUPERVISADA", 0, False)
    assert any("suspendida" in o for o in r["observaciones"])


def test_una_ong_no_registrada_se_informa_sin_fallar(client):
    r = _unico(client, "BAJO", "00-0-0", "RACION_ALIMENTO", 10)
    assert (r["ong"], r["nivel"], r["alcanza"]) == (None, "SUPERVISADA", False)
    assert "ONG no registrada en el Sistema Nacional" in r["observaciones"]


def test_varias_ongs_en_un_pedido_y_alcanza_todo(client):
    resp = _validar(client, "MEDIO", (CRUZ_ROJA, "PARAMEDICO", 4), (BOMBEROS, "RESCATISTA_ACUATICO", 12))
    assert [r["alcanza"] for r in resp["resultados"]] == [True, True]
    assert resp["alcanza_todo"] is True
    resp = _validar(client, "MEDIO", (CRUZ_ROJA, "PARAMEDICO", 4), (BOMBEROS, "RESCATISTA_ACUATICO", 13))
    assert resp["alcanza_todo"] is False


def test_tipo_de_recurso_inexistente_da_422(client):
    r = client.post("/validaciones", json={"gravedad": "ALTO", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "NADA", "cantidad": 1}]})
    assert r.status_code == 422
    assert "NADA" in r.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"gravedad": "ALTO", "items": []},
        {"gravedad": "ENORME", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 1}]},
        {"gravedad": "ALTO", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 0}]},
    ],
)
def test_entradas_invalidas_dan_422(client, body):
    assert client.post("/validaciones", json=body).status_code == 422


def test_validar_no_modifica_el_inventario(client):
    antes = client.get(f"/ongs/{CRUZ_ROJA}").json()
    _validar(client, "ALTO", (CRUZ_ROJA, "PARAMEDICO", 3))
    assert client.get(f"/ongs/{CRUZ_ROJA}").json() == antes


def test_la_certificacion_vigente_incluye_el_dia_del_vencimiento(seeded_db):
    db, vence = seeded_db
    item = [ItemValidacionIn(cuit=CRUZ_ROJA, tipo_recurso="PARAMEDICO", cantidad=1)]
    from app.models import Riesgo

    (hoy,) = validar(db, Riesgo.MEDIO, item, vence)
    (manana,) = validar(db, Riesgo.MEDIO, item, vence + timedelta(days=1))
    assert hoy.nivel == "PLENA"
    assert manana.nivel == "SUPERVISADA"


@pytest.fixture
def seeded_db(session_factory):
    from app.seed import seed

    seed(session_factory)
    with session_factory() as db:
        ong = db.scalar(select(Ong).where(Ong.cuit == CRUZ_ROJA))
        vence = date.today() + timedelta(days=10)
        ong.certificaciones[0].vence_el = vence
        db.commit()
        yield db, vence
