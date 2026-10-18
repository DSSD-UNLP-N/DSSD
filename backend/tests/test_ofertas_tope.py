"""La ONG no puede ofrecer más de lo que tiene: lo que ofrece de cada recurso se suma con sus otras
ofertas abiertas y se valida contra el inventario del Sistema Nacional (que va mockeado)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Emergencia, EstadoEmergencia, Gravedad, Lote, Municipio, Oferta, Ong
from tests.conftest import PASSWORD

CRUZ_ROJA = "30-54666544-5"  # 4 paramédicos en el FakeNacional


def _sin_zona(delta):
    # Como la guarda publicar_convocatoria: UTC sin zona (SQLite la descarta).
    return datetime.now(timezone.utc).replace(tzinfo=None) + delta


def _emergencia(seeded, *lotes, horas=2, gravedad=Gravedad.ALTO):
    """Convocatoria abierta con un lote por cada (tipo_recurso, cantidad)."""
    with seeded() as s:
        e = Emergencia(municipio_id=s.query(Municipio).one().id, tipo="inundacion", nivel_gravedad=gravedad,
                       zona_afectada="Centro", descripcion="d", bonita_case_id=None,
                       estado=EstadoEmergencia.CONVOCATORIA, ventana_ofertas_fin=_sin_zona(timedelta(hours=horas)))
        e.lotes = [Lote(recurso=tipo or "Libre", tipo_recurso=tipo, cantidad=cantidad, unidad="u")
                   for tipo, cantidad in lotes]
        s.add(e)
        s.commit()
        return e.id, [l.id for l in e.lotes]


@pytest.fixture
def api_login(client):
    def _login(username):
        client.post("/api/auth/logout")
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return client

    return _login


def _ofrecer(c, emergencia, *pares):
    """pares: (lote_id, cantidad)."""
    return c.post(f"/api/emergencias/{emergencia}/ofertas",
                  json={"items": [{"lote_id": l, "recurso": "x", "cantidad": n} for l, n in pares]})


def _ofertas(seeded):
    with seeded() as s:
        return s.query(Oferta).count()


def test_ofrecer_mas_de_lo_que_tiene_se_rechaza_y_no_guarda_nada(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 20))
    r = _ofrecer(api_login("ong.cruzroja"), em, (lote, 10))
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "No alcanza tu inventario. Paramédico: entre tus ofertas abiertas sumás 10 personas y tenés 4 disponibles.")
    assert _ofertas(seeded) == 0


def test_ofrecer_justo_lo_que_tiene_se_acepta(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 20))
    r = _ofrecer(api_login("ong.cruzroja"), em, (lote, 4))
    assert r.status_code == 201 and r.json()["version_actual"] == 1


def test_dos_lotes_del_mismo_recurso_se_suman(api_login, seeded):
    em, (a, b) = _emergencia(seeded, ("PARAMEDICO", 5), ("PARAMEDICO", 5))
    r = _ofrecer(api_login("ong.cruzroja"), em, (a, 2), (b, 3))  # 5 > 4
    assert r.status_code == 400 and "sumás 5 personas y tenés 4" in r.json()["detail"]
    assert _ofrecer(api_login("ong.cruzroja"), em, (a, 2), (b, 2)).status_code == 201


def test_el_caso_de_la_demo_2_y_despues_3_entre_emergencias(api_login, seeded):
    """Tiene 4: 2 en la emergencia 1 → ok; 3 en la 2 → rechazo (2+3=5);
    editar la 1 a 3 reemplaza (no suma); entonces en la 2 entra 1 pero no 2."""
    em1, (l1,) = _emergencia(seeded, ("PARAMEDICO", 10))
    em2, (l2,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    assert _ofrecer(c, em1, (l1, 2)).status_code == 201
    r = _ofrecer(c, em2, (l2, 3))
    assert r.status_code == 400 and "sumás 5 personas y tenés 4" in r.json()["detail"]
    assert _ofrecer(c, em1, (l1, 3)).status_code == 201
    assert _ofrecer(c, em2, (l2, 2)).status_code == 400
    assert _ofrecer(c, em2, (l2, 1)).status_code == 201


def test_cada_ong_tiene_su_propio_inventario(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 20))
    assert _ofrecer(api_login("ong.cruzroja"), em, (lote, 4)).status_code == 201
    assert _ofrecer(api_login("ong.bomberos"), em, (lote, 6)).status_code == 201  # Bomberos tiene 6
    assert _ofrecer(api_login("ong.bomberos"), em, (lote, 7)).status_code == 400


def test_una_convocatoria_vencida_sin_evaluar_sigue_comprometiendo_el_stock(api_login, seeded):
    vencida, (lv,) = _emergencia(seeded, ("PARAMEDICO", 10))
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    assert _ofrecer(api_login("ong.cruzroja"), vencida, (lv, 4)).status_code == 201
    with seeded() as s:  # la ventana vence después de haber ofertado; Bonita todavía no pidió el consolidado
        s.get(Emergencia, vencida).ventana_ofertas_fin = _sin_zona(-timedelta(minutes=1))
        s.commit()
    assert _ofrecer(api_login("ong.cruzroja"), em, (lote, 1)).status_code == 400


def test_en_evaluacion_la_reserva_ya_esta_en_la_api_nacional_y_no_cuenta_dos_veces(api_login, seeded):
    evaluada, (lv,) = _emergencia(seeded, ("PARAMEDICO", 10))
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    assert _ofrecer(api_login("ong.cruzroja"), evaluada, (lv, 4)).status_code == 201
    with seeded() as s:
        e = s.get(Emergencia, evaluada)
        e.ventana_ofertas_fin = _sin_zona(-timedelta(minutes=1))
        e.estado = EstadoEmergencia.EN_EVALUACION
        s.commit()
    assert _ofrecer(api_login("ong.cruzroja"), em, (lote, 4)).status_code == 201


def test_se_valida_contra_la_gravedad_de_la_emergencia_y_el_cuit_de_la_ong(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10), gravedad=Gravedad.CRITICO)
    _ofrecer(api_login("ong.cruzroja"), em, (lote, 2))
    ((gravedad, items),) = nacional.validaciones
    assert gravedad == "CRITICO"
    assert items == [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 2}]


def test_bajar_o_repetir_la_oferta_no_consulta_al_sistema_nacional(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    assert _ofrecer(c, em, (lote, 3)).status_code == 201
    assert len(nacional.validaciones) == 1
    assert _ofrecer(c, em, (lote, 3)).status_code == 201  # igual
    assert _ofrecer(c, em, (lote, 1)).status_code == 201  # menos
    assert len(nacional.validaciones) == 1


def test_los_lotes_sin_tipo_no_se_validan(api_login, seeded, nacional):
    em, (libre, tipado) = _emergencia(seeded, (None, 1000), ("PARAMEDICO", 10))
    assert _ofrecer(api_login("ong.cruzroja"), em, (libre, 999), (tipado, 2)).status_code == 201
    ((_, items),) = nacional.validaciones
    assert items == [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 2}]


def test_con_el_sistema_nacional_caido_no_se_publica_nada(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    nacional.caido = True
    r = _ofrecer(api_login("ong.cruzroja"), em, (lote, 1))
    assert r.status_code == 503 and "Sistema Nacional no responde" in r.json()["detail"]
    assert _ofertas(seeded) == 0


def test_sin_cuit_no_se_puede_validar_el_inventario(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    with seeded() as s:
        s.query(Ong).filter_by(nombre="Cruz Roja Argentina").one().cuit = None
        s.commit()
    r = _ofrecer(api_login("ong.cruzroja"), em, (lote, 1))
    assert r.status_code == 400 and "CUIT" in r.json()["detail"]


# --- retirar ---------------------------------------------------------------
# Retirar un lote = reenviar la oferta sin él (versión nueva); retirarla toda = reenviarla vacía.

def _items(seeded, emergencia):
    from app.models import OfertaItem

    with seeded() as s:
        oferta = s.query(Oferta).filter_by(emergencia_id=emergencia).one()
        return sorted((i.version, i.lote_id, i.cantidad) for i in s.query(OfertaItem).filter_by(oferta_id=oferta.id))


def test_retirar_un_lote_deja_una_version_sin_ese_item_y_conserva_el_historial(api_login, seeded):
    em, (a, b) = _emergencia(seeded, ("PARAMEDICO", 5), ("RACION_ALIMENTO", 100))
    c = api_login("ong.cruzroja")
    assert _ofrecer(c, em, (a, 2), (b, 50)).status_code == 201
    r = _ofrecer(c, em, (a, 2))  # retira el lote b
    assert r.status_code == 201
    assert (r.json()["version_actual"], [i["lote_id"] for i in r.json()["items"]], r.json()["retirada"]) == (2, [a], False)
    assert _items(seeded, em) == [(1, a, 2), (1, b, 50), (2, a, 2)]  # la v1 sigue intacta


def test_retirar_toda_la_oferta(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 5))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 3))
    r = _ofrecer(c, em)
    assert r.status_code == 201
    assert (r.json()["version_actual"], r.json()["items"], r.json()["retirada"]) == (2, [], True)
    assert _items(seeded, em) == [(1, lote, 3)]  # el historial no se pierde
    # el Coordinador la ve marcada como retirada
    (oferta,) = api_login("coordinador.regional").get(f"/api/emergencias/{em}/ofertas").json()
    assert oferta["retirada"] is True


def test_retirar_libera_el_cupo_para_otra_convocatoria(api_login, seeded):
    em1, (l1,) = _emergencia(seeded, ("PARAMEDICO", 10))
    em2, (l2,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    assert _ofrecer(c, em1, (l1, 4)).status_code == 201
    assert _ofrecer(c, em2, (l2, 3)).status_code == 400  # 4 + 3 > 4
    assert _ofrecer(c, em1).status_code == 201  # retira
    assert _ofrecer(c, em2, (l2, 3)).status_code == 201


def test_volver_a_ofertar_despues_de_retirar_se_valida_de_nuevo(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 2))
    _ofrecer(c, em)
    assert _ofrecer(c, em, (lote, 9)).status_code == 400
    r = _ofrecer(c, em, (lote, 4))
    assert (r.status_code, r.json()["version_actual"], r.json()["retirada"]) == (201, 3, False)


def test_retirar_no_depende_del_sistema_nacional(api_login, seeded, nacional):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 2))
    nacional.caido = True
    r = _ofrecer(c, em)
    assert r.status_code == 201 and r.json()["retirada"] is True
    assert len(nacional.validaciones) == 1  # solo la del alta


def test_no_se_puede_retirar_lo_que_no_se_ofreci(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    r = _ofrecer(c, em)
    assert r.status_code == 400 and "No tenés una oferta para retirar" in r.json()["detail"]
    assert _ofertas(seeded) == 0
    _ofrecer(c, em, (lote, 1))
    _ofrecer(c, em)
    assert _ofrecer(c, em).status_code == 400  # ya estaba retirada


def test_con_la_ventana_vencida_no_se_puede_retirar(api_login, seeded):
    em, (lote,) = _emergencia(seeded, ("PARAMEDICO", 10))
    c = api_login("ong.cruzroja")
    _ofrecer(c, em, (lote, 2))
    with seeded() as s:
        s.get(Emergencia, em).ventana_ofertas_fin = _sin_zona(-timedelta(minutes=1))
        s.commit()
    r = _ofrecer(c, em)
    assert r.status_code == 400 and "cerró" in r.json()["detail"]
