"""Validación de entrada de todos los endpoints: lo mal formado se rechaza con 4xx, nunca con 500 ni guardando basura."""
import pytest

CRUZ_ROJA = "30-54666544-5"
BOMBEROS = "30-68522415-9"
INEXISTENTE = "99-99999999-9"  # bien formado, no registrado
INT32 = 2_147_483_647
PASADO_DE_INT32 = INT32 + 1


def _registro(**cambios):
    cuerpo = {"ong_nombre": "ONG Nueva", "cuit": "30-71234567-8", "nombre": "Ana", "username": "ong.nueva", "password": "12345678"}
    return {**cuerpo, **cambios}


# --- CUIT: una sola forma canónica ---

@pytest.mark.parametrize("cuit", ["30712345678", " 30-71234567-8 ", "30-71234567-8", "3071234567-8"])
def test_el_registro_guarda_el_cuit_con_guiones(client, cuit):
    r = client.post("/ongs", json=_registro(cuit=cuit))
    assert r.status_code == 201, r.text
    assert r.json()["user"]["cuit"] == "30-71234567-8"
    assert client.get("/ongs/30-71234567-8").status_code == 200


def test_el_mismo_cuit_escrito_distinto_no_se_registra_dos_veces(client):
    assert client.post("/ongs", json=_registro(cuit="30712345678")).status_code == 201
    r = client.post("/ongs", json=_registro(cuit="30-71234567-8", ong_nombre="Otra ONG", username="ong.otra"))
    assert r.status_code == 409


@pytest.mark.parametrize("cuit", ["abc", "", "30-7123456-8", "30-712345678-8", "30-71234567-88", "3O-71234567-8"])
def test_el_registro_rechaza_cuit_mal_formado(client, cuit):
    assert client.post("/ongs", json=_registro(cuit=cuit)).status_code == 422


def test_la_ficha_y_el_inventario_aceptan_el_cuit_sin_guiones(client, ong_headers):
    assert client.get("/ongs/30546665445").json()["cuit"] == CRUZ_ROJA
    r = client.put("/ongs/30546665445/inventario", headers=ong_headers(CRUZ_ROJA),
                   json={"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 6}]})
    assert r.status_code == 200, r.text


def test_validaciones_cierres_y_evaluaciones_aceptan_el_cuit_sin_guiones(client):
    r = client.post("/validaciones", json={"gravedad": "ALTO", "items": [{"cuit": "30546665445", "tipo_recurso": "PARAMEDICO", "cantidad": 1}]})
    assert r.json()["resultados"][0]["ong"] == "Cruz Roja Argentina"
    assert client.post("/cierres", json={"cuit": " 30546665445 ", "referencia": "nada"}).status_code == 404  # llega a buscar la referencia


@pytest.mark.parametrize("cuit", ["abc", "", "30-1-2"])
def test_los_cuerpos_con_cuit_mal_formado_dan_422(client, cuit):
    item = {"cuit": cuit, "tipo_recurso": "PARAMEDICO", "cantidad": 1}
    assert client.post("/validaciones", json={"gravedad": "ALTO", "items": [item]}).status_code == 422
    assert client.post("/cierres", json={"cuit": cuit, "referencia": "x"}).status_code == 422
    assert client.post("/cierres/lote", json={"cierres": [{"cuit": cuit, "referencia": "x"}]}).status_code == 422
    oferta = {"cuit": cuit, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 1}]}
    assert client.post("/evaluaciones", json={"emergencia_id": 1, "gravedad": "ALTO", "lotes": [], "ofertas": [oferta]}).status_code == 422


# --- Registro: cuentas y nombres ---

@pytest.mark.parametrize("cambio", [
    {"username": "a b c"}, {"username": "ana@mail"}, {"username": "ñandú"}, {"password": "        "},
])
def test_el_registro_rechaza_usuario_o_clave_invalidos(client, cambio):
    assert client.post("/ongs", json=_registro(**cambio)).status_code == 422


def test_usuario_y_nombre_de_ong_no_distinguen_mayusculas(client):
    assert client.post("/ongs", json=_registro(username="ONG.CRUZROJA", cuit="30-71234567-8")).status_code == 409
    assert client.post("/ongs", json=_registro(ong_nombre="cruz roja argentina", cuit="30-71234567-8")).status_code == 409


# --- Enteros: más de 32 bits llegaría a Postgres y daría 500 ---

def test_el_inventario_rechaza_cantidades_que_no_entran_en_la_columna(client, ong_headers):
    r = client.put(f"/ongs/{CRUZ_ROJA}/inventario", headers=ong_headers(CRUZ_ROJA),
                   json={"items": [{"tipo_recurso": "FRAZADA", "cantidad_total": PASADO_DE_INT32}]})
    assert r.status_code == 422
    r = client.put(f"/ongs/{CRUZ_ROJA}/inventario", headers=ong_headers(CRUZ_ROJA),
                   json={"items": [{"tipo_recurso": "FRAZADA", "cantidad_total": INT32}]})
    assert r.status_code == 200


def test_el_inventario_rechaza_tipo_vacio_con_422(client, ong_headers):
    r = client.put(f"/ongs/{CRUZ_ROJA}/inventario", headers=ong_headers(CRUZ_ROJA),
                   json={"items": [{"tipo_recurso": "", "cantidad_total": 1}]})
    assert r.status_code == 422


def test_la_adjudicacion_directa_rechaza_enteros_fuera_de_rango_y_referencia_en_blanco(client):
    base = {"referencia_id": "x-1", "ong_id": 1, "emergencia_id": 1, "items": [{"inventario_id": 1, "cantidad": 1}]}
    for cambio in ({"emergencia_id": PASADO_DE_INT32}, {"ong_id": PASADO_DE_INT32}, {"referencia_id": "   "},
                   {"items": [{"inventario_id": PASADO_DE_INT32, "cantidad": 1}]},
                   {"items": [{"inventario_id": 1, "cantidad": PASADO_DE_INT32}]}):
        assert client.post("/adjudicaciones", json={**base, **cambio}).status_code == 422, cambio


def test_la_validacion_rechaza_tipo_vacio_y_cantidad_enorme(client):
    item = {"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 1}
    assert client.post("/validaciones", json={"gravedad": "ALTO", "items": [{**item, "tipo_recurso": ""}]}).status_code == 422
    assert client.post("/validaciones", json={"gravedad": "ALTO", "items": [{**item, "cantidad": 10**12}]}).status_code == 422


# --- Evaluaciones: el pedido tiene que ser coherente ---

LOTE = {"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 2, "tipo": "PRINCIPAL"}


def _evaluar(client, lotes=(LOTE,), items=None, emergencia=950):
    items = items if items is not None else [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 1}]
    return client.post("/evaluaciones", json={"emergencia_id": emergencia, "gravedad": "ALTO", "lotes": list(lotes),
                                              "ofertas": [{"cuit": CRUZ_ROJA, "items": items}]})


def _comprometido(client):
    ficha = client.get(f"/ongs/{CRUZ_ROJA}").json()
    return sum(i["cantidad_comprometida"] for i in ficha["inventario"])


def test_evaluar_rechaza_lotes_repetidos(client):
    assert _evaluar(client, lotes=(LOTE, LOTE)).status_code == 422


def test_evaluar_rechaza_un_tipo_de_lote_inexistente(client):
    assert _evaluar(client, lotes=({**LOTE, "tipo": "FOO"},)).status_code == 422


def test_evaluar_rechaza_ofrecer_a_un_lote_que_no_esta_en_el_pedido_y_no_reserva(client):
    r = _evaluar(client, items=[{"lote_id": 77, "tipo_recurso": "PARAMEDICO", "cantidad": 1}])
    assert r.status_code == 422
    assert _comprometido(client) == 0


def test_evaluar_rechaza_ofrecer_otro_recurso_que_el_del_lote_y_no_reserva(client):
    r = _evaluar(client, items=[{"lote_id": 1, "tipo_recurso": "AGUA_POTABLE", "cantidad": 1}])
    assert r.status_code == 422
    assert _comprometido(client) == 0


def test_evaluar_con_un_pedido_coherente_sigue_reservando(client):
    r = _evaluar(client)
    assert r.status_code == 200, r.text
    assert _comprometido(client) == 1


def test_evaluar_rechaza_ids_y_cantidades_fuera_de_rango(client):
    assert _evaluar(client, emergencia=PASADO_DE_INT32).status_code == 422
    assert _evaluar(client, lotes=({**LOTE, "cantidad": PASADO_DE_INT32},)).status_code == 422


# --- Lo que Postgres rechazaría con 500 y SQLite deja pasar ---

def test_un_caracter_nul_en_un_texto_se_rechaza_con_422(client):
    assert client.post("/cierres", json={"cuit": CRUZ_ROJA, "referencia": "a\u0000b"}).status_code == 422
    assert client.post("/login", json={"username": "a\u0000b", "password": "x"}).status_code == 422
    assert client.get("/recursos/disponibilidad", params={"tipo_recurso": "A\u0000"}).status_code == 422
    r = client.post("/validaciones", json={"gravedad": "MEDIO", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "A\u0000", "cantidad": 1}]})
    assert r.status_code == 422


def test_un_cuerpo_con_nan_da_422_y_no_500(client):
    r = client.post("/validaciones", content=b"NaN", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_el_id_de_un_cierre_pasado_de_int32_da_422(client):
    assert client.get(f"/cierres/{PASADO_DE_INT32}").status_code == 422
    assert client.get("/cierres/0").status_code == 422


def test_el_cuit_solo_admite_digitos_ascii(client):
    arabes = "٣٠-٥٤٦٦٦٥٤٤-٥"
    r = client.post("/validaciones", json={"gravedad": "MEDIO", "items": [{"cuit": arabes, "tipo_recurso": "FRAZADA", "cantidad": 1}]})
    assert r.status_code == 422
    assert client.post("/ongs", json=_registro(cuit=arabes)).status_code == 422
